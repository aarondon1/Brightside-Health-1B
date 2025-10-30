from neo4j import GraphDatabase

# Neo4j connection
NEO4J_URI = "bolt://localhost:7690"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

CONFIDENCE_THRESHOLD = 0.6  # relationships below this will be flagged

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def validate_relationships(tx):
    # Find relationships below confidence threshold
    low_conf = tx.run("""
        MATCH (d:Drug)-[r]->(t)
        WHERE r.confidence IS NOT NULL AND r.confidence < $threshold
        RETURN d.id AS drug_id, type(r) AS rel_type, t.id AS target_id, r.confidence AS confidence
    """, {"threshold": CONFIDENCE_THRESHOLD})

    
    low_conf_list = [record.data() for record in low_conf]

    # Find duplicate relationships (same start, type, end)
    duplicates = tx.run("""
        MATCH (d:Drug)-[r]->(t)
        WITH d, t, type(r) AS rel_type, collect(r) AS rels
        WHERE size(rels) > 1
        RETURN d.id AS drug_id, rel_type, t.id AS target_id, size(rels) AS duplicate_count
    """)
    
    duplicates_list = [record.data() for record in duplicates]

    return low_conf_list, duplicates_list

with driver.session() as session:
    low_conf_edges, duplicate_edges = session.execute_read(validate_relationships)

driver.close()

# Print results
print("=== Low-Confidence Relationships ===")
if low_conf_edges:
    for r in low_conf_edges:
        print(r)
else:
    print("None found")

print("\n=== Duplicate Relationships ===")
if duplicate_edges:
    for r in duplicate_edges:
        print(r)
else:
    print("None found")

# run scrip with: 
#   python3 scripts/neo4j_validate.py