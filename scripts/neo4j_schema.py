import json
from neo4j import GraphDatabase

# Neo4j connection config
NEO4J_URI = "bolt://localhost:7690"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

SAMPLE_LIMIT = 3  # how many sample nodes to display per label

def get_schema_with_samples(uri, user, password):
    driver = GraphDatabase.driver(uri, auth=(user, password))
    
    with driver.session() as session:
        # 1. Node labels
        labels_result = session.run("CALL db.labels()")
        node_labels = [record["label"] for record in labels_result]
        
        # 2. Relationship types
        rel_result = session.run("CALL db.relationshipTypes()")
        relationship_types = [record["relationshipType"] for record in rel_result]
        
        # 3. Node property keys
        node_properties = {}
        for label in node_labels:
            prop_result = session.run(f"MATCH (n:{label}) UNWIND keys(n) AS key RETURN collect(DISTINCT key) AS props")
            record = prop_result.single()
            node_properties[label] = record["props"] if record else []

        # 4. Relationship property keys
        relationship_properties = {}
        for rel_type in relationship_types:
            rel_prop_result = session.run(
                f"""
                MATCH ()-[r:{rel_type}]->()
                UNWIND keys(r) AS key
                RETURN collect(DISTINCT key) AS props
                """
            )
            record = rel_prop_result.single()
            relationship_properties[rel_type] = record["props"] if record else []

        # 5. Sample nodes with relationships including confidence levels
        sample_nodes_with_rels = {}
        for label in node_labels:
            sample_nodes_with_rels[label] = []
            node_result = session.run(f"MATCH (n:{label}) RETURN n LIMIT {SAMPLE_LIMIT}")
            for node_record in node_result:
                node = dict(node_record["n"])
                
                # outgoing relationships including confidence
                rel_result = session.run(
                    f"""
                    MATCH (n:{label} {{id: $id}})-[r]->(m)
                    RETURN type(r) AS rel_type, labels(m) AS target_labels, m AS target_node, properties(r) AS rel_props
                    """,
                    {"id": node.get("id")}
                )
                relationships = []
                for rel in rel_result:
                    relationships.append({
                        "type": rel["rel_type"],
                        "target_labels": rel["target_labels"],
                        "target_node": dict(rel["target_node"]),
                        "properties": dict(rel["rel_props"])  # properties of relationship (confidence level, section, etc.)
                    })
                
                sample_nodes_with_rels[label].append({
                    "node": node,
                    "relationships": relationships
                })
    
    driver.close()
    
    # Print results
    print("\n=== SCHEMA OVERVIEW ===")
    print(f"Node Labels: {node_labels}")
    print(f"Relationship Types: {relationship_types}")
    
    print("\n=== NODE PROPERTY KEYS ===")
    for label, props in node_properties.items():
        print(f"  {label}: {props}")
    
    print("\n=== RELATIONSHIP PROPERTY KEYS ===")
    for rel_type, props in relationship_properties.items():
        print(f"  {rel_type}: {props}")
    
    print("\n=== SAMPLE NODES WITH RELATIONSHIPS ===")
    for label, samples in sample_nodes_with_rels.items():
        print(f"\nLabel: {label}")
        for sample in samples:
            print(f"Node: {sample['node']}")
            if sample['relationships']:
                print("  Relationships:")
                for rel in sample['relationships']:
                    props_str = ", ".join(f"{k}: {v}" for k, v in rel["properties"].items())
                    print(f"    - {rel['type']} -> {rel['target_labels']} : {rel['target_node']} | Properties: {props_str}\n")
            else:
                print("  Relationships: None")
       
if __name__ == "__main__":
    get_schema_with_samples(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)


"""
This function is to print out the expected schema mapping for reference.
"""
def print_schema_mapping():
    schema_mapping = [
        ("Drug", "TREATS", "Condition", "Main treatment relationships"),
        ("Drug", "IMPROVES", "Outcome", "Drug improves an outcome"),
        ("Drug", "AUGMENTS", "Drug", "Drug augments another drug"),
        ("Drug", "CONTRAINDICATED_FOR", "Condition", "Drug should not be used for condition"),
        ("Drug", "SUPERIOR_TO", "Drug", "Drug is better than another drug"),
        ("Drug", "EQUIVALENT_TO", "Drug", "Drug equivalent to another drug"),
        ("Condition", "ASSOCIATED_WITH_SE", "Outcome", "Side effects associated with condition"),
        ("Outcome", "-", "-", "Outcomes are generally terminal nodes")
    ]

    print("\n=== NODE → RELATIONSHIP → NODE SCHEMA ===\n")
    print(f"{'Source Node':<12} {'Relationship Type':<22} {'Target Node':<12} {'Notes'}")
    print("-" * 80)
    for src, rel, tgt, note in schema_mapping:
        print(f"{src:<12} {rel:<22} {tgt:<12} {note}")

if __name__ == "__main__":
    print_schema_mapping()


# run scrip with: 
#   python3 scripts/neo4j_schema.py