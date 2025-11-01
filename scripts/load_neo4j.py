import json
from neo4j import GraphDatabase
import argparse
import os
import sys
import hashlib

# Define all valid relationship types
VALID_RELATIONS = {
    "TREATS", "IMPROVES", "ASSOCIATED_WITH_SE", "AUGMENTS", 
    "CONTRAINDICATED_FOR", "SUPERIOR_TO", "EQUIVALENT_TO", "INFERIOR_TO"
}

# Mapping for human-readable relationship labels
RELATION_LABELS = {
    "TREATS": "treats",
    "IMPROVES": "improves",
    "ASSOCIATED_WITH_SE": "associated_with_side_effect",
    "AUGMENTS": "augments",
    "CONTRAINDICATED_FOR": "contraindicated_for",
    "SUPERIOR_TO": "superior_to",
    "EQUIVALENT_TO": "equivalent_to",
    "INFERIOR_TO": "inferior_to"
}

# Neo4j connection configuration
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

class Neo4jLoader:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    def clear_database(self):
        """Clear all existing data from the database"""
        with self.driver.session() as session:
            session.execute_write(self._clear_all_data)
            print("Database cleared")
    
    @staticmethod
    def _clear_all_data(tx):
        tx.run("MATCH (n) DETACH DELETE n")

def generate_node_id(prefix, text, concept_id):
    """Generate unique node ID
    example output: "id: drug_RXNORM_72625" or "id: condition_unmatched_5fa7cc34"
    """
    if concept_id:
        clean_id = concept_id.replace(':', '_').replace('/', '_').replace(' ', '_')
        return f"{prefix}_{clean_id}"
    else:
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{prefix}_unmatched_{text_hash}"

def load_normalized_data(loader, normalized_file):
    """Load normalized JSON data into Neo4j with readable nodes/relationships"""
    try:
        with open(normalized_file, 'r') as f:
            data = json.load(f)
        
        facts = data['normalized_facts']
        print(f"Loading {len(facts)} normalized facts into Neo4j...")

        nodes_created = set()
        relationships_created = 0
        relationship_counts = {rel: 0 for rel in VALID_RELATIONS}

        for i, fact in enumerate(facts):
            if i % 10 == 0:
                print(f"  Processing fact {i+1}/{len(facts)}...")

            raw_fact = fact.get('raw_fact', {})
            
            with loader.driver.session() as session:
                result = session.execute_write(
                    _process_fact_complete, 
                    fact, raw_fact, nodes_created, relationship_counts
                )
                
                if result:
                    new_nodes, new_rels = result
                    nodes_created.update(new_nodes)
                    relationships_created += new_rels

        print(f"\nCreated {len(nodes_created)} nodes and {relationships_created} relationships\n")
        print("RELATIONSHIP BREAKDOWN:")
        for rel_type, count in relationship_counts.items():
            if count > 0:
                print(f"  {RELATION_LABELS[rel_type]} ({rel_type}): {count}")

    except Exception as e:
        print(f"Error loading data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def _process_fact_complete(tx, fact, raw_fact, existing_nodes, rel_counts):
    """Process a single fact with nodes/relationships"""
    new_nodes = set()
    relationships_created = 0

    drug_match = fact.get('drug', {})
    condition_match = fact.get('condition', {})
    outcome_match = fact.get('outcome', {})

    # ----- CREATE NODES -----
    def create_node(label, prefix, match):
        if match and match.get('text'):
            node_id = generate_node_id(prefix, match['text'], match.get('concept_id'))
            if node_id not in existing_nodes:
                tx.run(f"""
                    MERGE (n:{label} {{id: $id}})
                    SET n.name = $name,
                        n.normalized_name = $normalized_name,
                        n.match_type = $match_type,
                        n.match_score = $match_score,
                        n.category = $category
                """, {
                    "id": node_id,
                    "name": match.get('text', ''),
                    "normalized_name": match.get('label', ''),
                    "match_type": match.get('match_type', 'unmatched'),
                    "match_score": float(match.get('score', 0.0)),
                    "category": label
                })
                new_nodes.add(node_id)
            return node_id
        return None

    drug_id = create_node("Drug", "drug", drug_match)
    condition_id = create_node("Condition", "condition", condition_match)
    outcome_id = create_node("Outcome", "outcome", outcome_match)

    # ----- CREATE RELATIONSHIPS -----
    relation_type = fact.get('relation', {}).get('text', '')
    if relation_type not in VALID_RELATIONS:
        return new_nodes, relationships_created

    rel_label = RELATION_LABELS.get(relation_type, relation_type.lower())
    target_id = None
    if relation_type == "IMPROVES":
        target_id = outcome_id
    else:
        target_id = condition_id

    if drug_id and target_id:
        relationship_data = {
            "evidence": raw_fact.get('span', ''),
            "confidence": float(raw_fact.get('confidence', 0.0)),
            "source_text": raw_fact.get('span', ''),
            "source_id": raw_fact.get('source_id', ''),
            "section": raw_fact.get('section', '')
        }

        tx.run(f"""
            MATCH (d:Drug {{id: $drug_id}}), (t {{id: $target_id}})
            MERGE (d)-[r:{relation_type}]->(t)
            SET r.label = $rel_label, r += $props
        """, {
            "drug_id": drug_id,
            "target_id": target_id,
            "rel_label": rel_label,
            "props": relationship_data
        })

        relationships_created += 1
        rel_counts[relation_type] += 1

    return new_nodes, relationships_created

def main():
    parser = argparse.ArgumentParser(description='Load normalized data into Neo4j graph database')
    parser.add_argument('--input', required=True, help='Input normalized JSON file')
    parser.add_argument('--clear', action='store_true', help='Clear existing data before loading')
    parser.add_argument('--uri', default=NEO4J_URI, help='Neo4j connection URI')
    parser.add_argument('--user', default=NEO4J_USER, help='Neo4j username')
    parser.add_argument('--password', default=NEO4J_PASSWORD, help='Neo4j password')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    print(f"Loading data into Neo4j Browser at {args.uri}...")
    print(f"Input file: {args.input}")

    try:
        loader = Neo4jLoader(args.uri, args.user, args.password)
        
        if args.clear:
            loader.clear_database()
        
        load_normalized_data(loader, args.input)

        # ----- DATABASE SUMMARY -----
        print("\nFINAL DATABASE SUMMARY:")
        with loader.driver.session() as session:
            for label in ["Drug", "Condition", "Outcome"]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) AS count")
                print(f"  {label}s: {result.single()['count']}")

        loader.close()
        print("\nNeo4j database loaded successfully! Explore it in Neo4j Browser.")
    except Exception as e:
        print(f"Database error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
# Step 1: clear DB and load the first paper, (please change the file name accordingly)
python3 scripts/load_neo4j.py --input data/processed/normalized/sample_normalized_v4.json --clear

# Step 2: load the second paper (append)
python3 scripts/load_neo4j.py \
  --input data/processed/normalized/paper2_normalized.json

# Step 3: load the third paper (append)
python3 scripts/load_neo4j.py \
  --input data/processed/normalized/paper3_normalized.json
"""