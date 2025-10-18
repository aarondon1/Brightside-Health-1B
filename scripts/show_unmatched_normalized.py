#!/usr/bin/env python3
"""
Show unmatched items from normalization to help expand mappings.yaml
Usage: python3 -m scripts.show_unmatched --input data/processed/normalized/sample_normalizedv3.json
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

def main():
    parser = argparse.ArgumentParser(description="Analyze unmatched items from normalization")
    parser.add_argument("--input", required=True, help="Path to normalized facts JSON")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ File not found: {args.input}")
        sys.exit(1)
    
    # Load normalized facts
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Handle different JSON structures
    if isinstance(data, list):
        facts = data
    elif "normalized_facts" in data:
        facts = data["normalized_facts"]
    else:
        print("❌ Unexpected JSON structure")
        sys.exit(1)
    
    # Collect unmatched items
    unmatched_drugs = []
    unmatched_conditions = []
    unmatched_outcomes = []
    unmatched_side_effects = []
    
    for fact in facts:
        # Check drug
        if fact.get("drug", {}).get("match_type") == "unmatched":
            unmatched_drugs.append(fact["drug"]["text"])
        
        # Check condition
        if fact.get("condition", {}).get("match_type") == "unmatched":
            unmatched_conditions.append(fact["condition"]["text"])
        
        # Check outcome
        outcome = fact.get("outcome")
        if outcome and outcome.get("match_type") == "unmatched":
            unmatched_outcomes.append(outcome["text"])
        
        # Check side effects
        for se in fact.get("side_effects", []):
            if se.get("match_type") == "unmatched":
                unmatched_side_effects.append(se["text"])
    
    # Count occurrences
    drug_counts = Counter(unmatched_drugs)
    condition_counts = Counter(unmatched_conditions)
    outcome_counts = Counter(unmatched_outcomes)
    se_counts = Counter(unmatched_side_effects)
    
    # Print results
    print("=" * 70)
    print("🔍 UNMATCHED ITEMS REPORT")
    print("=" * 70)
    
    if drug_counts:
        print(f"\n❌ UNMATCHED DRUGS ({len(drug_counts)} unique, {len(unmatched_drugs)} total):")
        print("-" * 70)
        for drug, count in drug_counts.most_common():
            print(f"  [{count:2}x] {drug}")
    else:
        print("\n✅ All drugs matched!")
    
    if condition_counts:
        print(f"\n❌ UNMATCHED CONDITIONS ({len(condition_counts)} unique, {len(unmatched_conditions)} total):")
        print("-" * 70)
        for cond, count in condition_counts.most_common():
            print(f"  [{count:2}x] {cond}")
    else:
        print("\n✅ All conditions matched!")
    
    if outcome_counts:
        print(f"\n❌ UNMATCHED OUTCOMES ({len(outcome_counts)} unique, {len(unmatched_outcomes)} total):")
        print("-" * 70)
        for outcome, count in outcome_counts.most_common(20):  # Show top 20
            print(f"  [{count:2}x] {outcome}")
        if len(outcome_counts) > 20:
            print(f"  ... and {len(outcome_counts) - 20} more")
    else:
        print("\n✅ All outcomes matched!")
    
    if se_counts:
        print(f"\n❌ UNMATCHED SIDE EFFECTS ({len(se_counts)} unique, {len(unmatched_side_effects)} total):")
        print("-" * 70)
        for se, count in se_counts.most_common():
            print(f"  [{count:2}x] {se}")
    else:
        print("\n✅ All side effects matched!")
    
    print("\n" + "=" * 70)
    print("💡 NEXT STEPS:")
    print("=" * 70)
    print("1. Copy the unmatched items above")
    print("2. Add them to configs/mappings.yaml under the appropriate section")
    print("3. Run normalization again to verify 95%+ match rate")
    print()
    print("Example entry for mappings.yaml:")
    
    if drug_counts:
        first_drug = list(drug_counts.keys())[0]
        print(f"""
  - id: CUSTOM:DRUG_NEW
    label: {first_drug}
    provider: custom
    synonyms:
      - {first_drug.lower()}
""")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())