import json
from neo4j import GraphDatabase
import argparse
import os
import sys
from pathlib import Path
import hashlib

# Define all valid relationship types
VALID_RELATIONS = {
    "TREATS", "IMPROVES", "ASSOCIATED_WITH_SE", "AUGMENTS", 
    "CONTRAINDICATED_FOR", "SUPERIOR_TO", "EQUIVALENT_TO", "INFERIOR_TO"
}

# Neo4j connection configuration
NEO4J_URI = "bolt://localhost:7689"
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
    """Generate unique node ID"""
    if concept_id:
        clean_id = concept_id.replace(':', '_').replace('/', '_').replace(' ', '_')
        return f"{prefix}_{clean_id}"
    else:
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{prefix}_unmatched_{text_hash}"

def load_normalized_data(loader, normalized_file):
    """Load normalized JSON data into Neo4j with ALL relationship types"""
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
            
            # Process in transaction
            with loader.driver.session() as session:
                result = session.execute_write(
                    _process_fact_complete, 
                    fact, raw_fact, nodes_created, relationship_counts
                )
                
                if result:
                    new_nodes, new_rels = result
                    nodes_created.update(new_nodes)
                    relationships_created += new_rels

        print(f"Created {len(nodes_created)} nodes and {relationships_created} relationships")
        
        # Print relationship breakdown
        print(f"\n RELATIONSHIP BREAKDOWN:")
        for rel_type, count in relationship_counts.items():
            if count > 0:
                print(f"   {rel_type}: {count}")

    except Exception as e:
        print(f"Error loading data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def _process_fact_complete(tx, fact, raw_fact, existing_nodes, rel_counts):
    """Process a single fact with ALL relationship types"""
    new_nodes = set()
    relationships_created = 0
    
    # Create nodes first
    drug_match = fact.get('drug', {})
    condition_match = fact.get('condition', {})
    outcome_match = fact.get('outcome', {})
    
    # Create Drug node
    if drug_match and drug_match.get('text'):
        drug_id = generate_node_id("drug", drug_match['text'], drug_match.get('concept_id'))
        if drug_id not in existing_nodes:
            tx.run("""
                MERGE (d:Drug {id: $id}) 
                SET d.name = $name, 
                    d.normalized_name = $normalized_name,
                    d.rxnorm_id = $rxnorm_id,
                    d.match_type = $match_type,
                    d.match_score = $match_score
            """, {
                "id": drug_id,
                "name": drug_match.get('text', ''),
                "normalized_name": drug_match.get('label', ''),
                "rxnorm_id": drug_match.get('concept_id', ''),
                "match_type": drug_match.get('match_type', 'unmatched'),
                "match_score": float(drug_match.get('score', 0.0))
            })
            new_nodes.add(drug_id)

    # Create Condition node
    if condition_match and condition_match.get('text'):
        condition_id = generate_node_id("condition", condition_match['text'], condition_match.get('concept_id'))
        if condition_id not in existing_nodes:
            tx.run("""
                MERGE (c:Condition {id: $id})
                SET c.name = $name, 
                    c.normalized_name = $normalized_name,
                    c.snomed_ct = $snomed_ct,
                    c.match_type = $match_type,
                    c.match_score = $match_score
            """, {
                "id": condition_id,
                "name": condition_match.get('text', ''),
                "normalized_name": condition_match.get('label', ''),
                "snomed_ct": condition_match.get('concept_id', ''),
                "match_type": condition_match.get('match_type', 'unmatched'),
                "match_score": float(condition_match.get('score', 0.0))
            })
            new_nodes.add(condition_id)

    # Create Outcome node
    if outcome_match and outcome_match.get('text'):
        outcome_id = generate_node_id("outcome", outcome_match['text'], outcome_match.get('concept_id'))
        if outcome_id not in existing_nodes:
            tx.run("""
                MERGE (o:Outcome {id: $id})
                SET o.name = $name,
                    o.normalized_name = $normalized_name,
                    o.match_type = $match_type,
                    o.match_score = $match_score
            """, {
                "id": outcome_id,
                "name": outcome_match.get('text', ''),
                "normalized_name": outcome_match.get('label', ''),
                "match_type": outcome_match.get('match_type', 'unmatched'),
                "match_score": float(outcome_match.get('score', 0.0))
            })
            new_nodes.add(outcome_id)

    # Create relationships for ALL types
    relation_match = fact.get('relation', {})
    relation_type = relation_match.get('text', '')
    
    if relation_type not in VALID_RELATIONS:
        return new_nodes, relationships_created
    
    # Get node IDs
    drug_id = generate_node_id("drug", drug_match['text'], drug_match.get('concept_id')) if drug_match.get('text') else None
    condition_id = generate_node_id("condition", condition_match['text'], condition_match.get('concept_id')) if condition_match.get('text') else None
    outcome_id = generate_node_id("outcome", outcome_match['text'], outcome_match.get('concept_id')) if outcome_match and outcome_match.get('text') else None
    
    # Create relationship based on type
    relationship_data = {
        "evidence": raw_fact.get('span', ''),
        "confidence": float(raw_fact.get('confidence', 0.0)),
        "source_text": raw_fact.get('span', ''),
        "source_id": raw_fact.get('source_id', ''),
        "section": raw_fact.get('section', '')
    }
    
    try:
        if relation_type == "TREATS" and drug_id and condition_id:
            tx.run(f"""
                MATCH (d:Drug {{id: $drug_id}}), (c:Condition {{id: $condition_id}})
                MERGE (d)-[r:{relation_type}]->(c)
                SET r += $props
            """, {
                "drug_id": drug_id,
                "condition_id": condition_id,
                "props": relationship_data
            })
            relationships_created += 1
            rel_counts[relation_type] += 1

        elif relation_type == "IMPROVES" and drug_id and outcome_id:
            tx.run(f"""
                MATCH (d:Drug {{id: $drug_id}}), (o:Outcome {{id: $outcome_id}})
                MERGE (d)-[r:{relation_type}]->(o)
                SET r += $props
            """, {
                "drug_id": drug_id,
                "outcome_id": outcome_id,
                "props": relationship_data
            })
            relationships_created += 1
            rel_counts[relation_type] += 1

        elif relation_type in ["ASSOCIATED_WITH_SE", "AUGMENTS", "CONTRAINDICATED_FOR"] and drug_id and condition_id:
            tx.run(f"""
                MATCH (d:Drug {{id: $drug_id}}), (c:Condition {{id: $condition_id}})
                MERGE (d)-[r:{relation_type}]->(c)
                SET r += $props
            """, {
                "drug_id": drug_id,
                "condition_id": condition_id,
                "props": relationship_data
            })
            relationships_created += 1
            rel_counts[relation_type] += 1

        elif relation_type in ["SUPERIOR_TO", "EQUIVALENT_TO", "INFERIOR_TO"] and drug_id and condition_id:
            # For drug comparisons, we'll link to condition for now
            # In a real implementation, you'd need a second drug node
            tx.run(f"""
                MATCH (d:Drug {{id: $drug_id}}), (c:Condition {{id: $condition_id}})
                MERGE (d)-[r:{relation_type}]->(c)
                SET r += $props
            """, {
                "drug_id": drug_id,
                "condition_id": condition_id,
                "props": relationship_data
            })
            relationships_created += 1
            rel_counts[relation_type] += 1
            
    except Exception as e:
        print(f"Error creating {relation_type} relationship: {e}")

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

    print(f" Loading relationship types into Neo4j...")
    print(f" Input data: {args.input}")
    print(f" Neo4j Browser URI: {args.uri}")

    try:
        loader = Neo4jLoader(args.uri, args.user, args.password)
        
        if args.clear:
            loader.clear_database()
        
        load_normalized_data(loader, args.input)

        # Final verification
        print("\n FINAL DATABASE SUMMARY detected:")
        with loader.driver.session() as session:
            result = session.run("MATCH (d:Drug) RETURN count(d) as drug_count")
            print(f"   Drugs: {result.single()['drug_count']}")

            result = session.run("MATCH (c:Condition) RETURN count(c) as condition_count")
            print(f"   Conditions: {result.single()['condition_count']}")

            result = session.run("MATCH (o:Outcome) RETURN count(o) as outcome_count")
            print(f"   Outcomes: {result.single()['outcome_count']}")
            
            print(f"\n RELATIONSHIP COUNTS:")
            for rel_type in VALID_RELATIONS:
                result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count")
                record = result.single()
                if record and record['count'] > 0:
                    print(f"   {rel_type}: {record['count']}")

        loader.close()
        print(f"\n Neo4j database loaded with ALL relationship types!\n You can now explore the data in Neo4j Browser at {args.uri}")

    except Exception as e:
        print(f" Database error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
Run this script with:
python3 scripts/load_neo4j.py --input data/processed/normalized/sample_normalized_v4.json --clear
"""