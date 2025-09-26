import json
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError

# Allowed relationship types - INCLUDING YOUR CUSTOM ONES
ALLOWED_RELATIONS = {
    "TREATS",               # Drug -> Condition
    "IMPROVES",             # Drug -> Condition
    "ASSOCIATED_WITH_SE",   # Drug -> Side Effect
    "AUGMENTS",             # Drug -> Condition (positive effect)
    "CONTRAINDICATED_FOR",  # Drug -> Condition (negative)
    "SUPERIOR_TO",          # Drug -> Drug (better efficacy)
    "EQUIVALENT_TO",        # Drug -> Drug
}

class ValidatedFact(BaseModel):
    """Simple validated fact model"""
    drug: str = Field(..., min_length=1)
    condition: str = Field(..., min_length=1) 
    relation: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    section: str
    evidence: str

class ValidationResult(BaseModel):
    """Results of the validation process"""
    valid_facts: List[Dict[str, Any]]
    total_input: int
    total_valid: int
    low_confidence: int
    invalid_relations: int
    validation_time: str

def load_extraction_data(file_path: str) -> Dict[str, Any]:
    """Load extracted facts from JSON file sample_extracted.json"""
    with open(file_path, 'r') as f:
        return json.load(f)

def validate_single_fact(fact: Dict[str, Any], min_confidence: float = 0.6) -> Dict[str, Any]:
    """
    Validate single extracted fact
    Returns validated fact if valid, None if invalid or low confidence
    """
    try:
        # Basic checks
        if not fact.get('drug_name') or not fact.get('condition_name'):
            print(f"   Missing drug/condition: {fact.get('drug_name')} -> {fact.get('condition_name')}")
            return None
        
        # skip if lower than 0.6
        if fact.get('confidence', 0) < min_confidence:
            print(f"   Low confidence: {fact.get('drug_name')} ({fact.get('confidence')})")
            return None
            
        relation = fact.get('relation')
        if relation not in ALLOWED_RELATIONS:
            print(f"   Invalid relation: {fact.get('drug_name')} -> {relation}")
            return None
        
        # Create clean fact
        clean_fact = {
            'drug': fact['drug_name'],
            'condition': fact['condition_name'],
            'relation': relation,
            'confidence': fact['confidence'],
            'source': fact.get('source_id', 'unknown'),
            'section': fact.get('section', 'unknown'),
            'evidence': fact.get('span', ''),
            'outcome': fact.get('outcome'),
            'side_effects': fact.get('side_effects', []),
            'effect_size': fact.get('effect_size')
        }
        
        # Validate with Pydantic
        ValidatedFact(**clean_fact)
        return clean_fact
        
    except (ValidationError, KeyError, TypeError) as e:
        print(f"   Validation error for {fact.get('drug_name')}: {e}")
        return None

def validate_extracted_facts(extraction_data: Dict[str, Any], 
                           min_confidence: float = 0.6) -> ValidationResult:
    """
    Main validation function to crosscheck extracted facts
    """
    raw_facts = extraction_data.get('extracted_facts', [])
    
    valid_facts = []
    low_confidence_count = 0
    invalid_relation_count = 0
    
    print(f"    Validating {len(raw_facts)} extracted facts...")
    print(f"    Allowed relations: {', '.join(sorted(ALLOWED_RELATIONS))}")
    print()
    
    for i, fact in enumerate(raw_facts, 1):
        # Skip if low confidence
        if fact.get('confidence', 0) < min_confidence:
            low_confidence_count += 1
            continue
            
        #skip if invalid relation
        if fact.get('relation') not in ALLOWED_RELATIONS:
            invalid_relation_count += 1
            continue
            
        # Validate the fact
        validated = validate_single_fact(fact, min_confidence)
        if validated:
            valid_facts.append(validated)
            print(f"   Valid: {fact.get('drug_name')} -> {fact.get('relation')} -> {fact.get('condition_name')}")
    
    # Create result
    result = ValidationResult(
        valid_facts=valid_facts,
        total_input=len(raw_facts),
        total_valid=len(valid_facts),
        low_confidence=low_confidence_count,
        invalid_relations=invalid_relation_count,
        validation_time=datetime.now().isoformat()
    )
    
    return result

def save_validation_results(results: ValidationResult, output_path: str):
    """Save validation results to JSON sample_validated.json"""
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results.model_dump(), f, indent=2)
    
    print(f"Saved validated data to {output_path}\n")

def print_validation_summary(results: ValidationResult):
    """Print a clean summary of validation results"""
    print("\n" + "==================================================")
    print("VALIDATION SUMMARY")
    print("==================================================")
    print(f"Total facts processed: {results.total_input}")
    print(f"          Valid facts: {results.total_valid}")
    print(f"       Low confidence: {results.low_confidence}")
    print(f"    Invalid relations: {results.invalid_relations}")
    
    # Show relation breakdown
    if results.valid_facts:
        relations = {}
        for fact in results.valid_facts:
            rel = fact['relation']
            relations[rel] = relations.get(rel, 0) + 1
        
        print("\n Relations found:")
        for rel, count in sorted(relations.items()):
            print(f"   {rel}: {count} facts")

def analyze_invalid_relations(extraction_data: Dict[str, Any]):
    """Show what relations are being filtered out"""
    raw_facts = extraction_data.get('extracted_facts', [])
    
    invalid_relations = {}
    for fact in raw_facts:
        relation = fact.get('relation')
        if relation not in ALLOWED_RELATIONS:
            invalid_relations[relation] = invalid_relations.get(relation, 0) + 1
    
    if invalid_relations:
        print("\n   Invalid relations found (add to ALLOWED_RELATIONSHIPS if valid):")
        for rel, count in sorted(invalid_relations.items()):
            print(f"   '{rel}': {count} facts")

def main():
    """Main function to run validation pipeline"""
    # change these path to run locally
    input_file = "/Users/guanying/Brightside Health 1B/Brightside-Health-1B/data/processed/extracted/sample_extracted.json"
    output_file = "/Users/guanying/Brightside Health 1B/Brightside-Health-1B/data/processed/validated/sample_validated.json"
    
    try:
        # 1. Load data
        print("     Loading extracted facts...")
        extraction_data = load_extraction_data(input_file)
        
        # 2. analyze what relations we have
        analyze_invalid_relations(extraction_data)
        print()
        
        # 3. Validate with lower confidence to see more results
        results = validate_extracted_facts(extraction_data, min_confidence=0.5)
        
        # 4. Save results
        save_validation_results(results, output_file)
        
        # 5. summary
        print_validation_summary(results)
                
    except FileNotFoundError:
        print(f"Error: Input file not found at {input_file}")
        print("Make sure to run extraction first!")
    except Exception as e:
        print(f"Validation error: {e}")

if __name__ == "__main__":
    main()

# TO run script: 
# Change the above file paths to your local paths
# Run in terminal: python src/core/validate.py