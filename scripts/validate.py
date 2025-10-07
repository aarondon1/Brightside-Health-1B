#!/usr/bin/env python3
"""
Validate extracted clinical facts for quality and consistency.
python -m scripts.validate --input data/processed/extracted/sample_extracted.json --output data/processed/validated/sample_extracted_validated.json --issues data/processed/validated/sample_extracted_issues.json --show-details
"""

import argparse
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.validate import validate_extracted_facts, save_validation_results

def main():
    parser = argparse.ArgumentParser(description="Validate extracted clinical facts")
    parser.add_argument("--input", required=True, help="Path to extracted facts JSON file")
    parser.add_argument("--output", help="Path for validated facts output (auto-generated if not provided)")
    parser.add_argument("--issues", help="Path to save detailed validation issues report")
    parser.add_argument("--show-details", action="store_true", help="Show detailed validation issues")
    
    args = parser.parse_args()
    
    # Auto-generate output path if not provided
    if not args.output:
        input_path = Path(args.input)
        output_dir = Path("data/processed/validated")
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = output_dir / f"{input_path.stem}_validated.json"
    
    # Auto-generate issues path if not provided but --show-details requested
    if args.show_details and not args.issues:
        output_path = Path(args.output)
        args.issues = output_path.parent / f"{output_path.stem}_issues.json"
    
    # Validate input file exists
    if not Path(args.input).exists():
        print(f"❌ Input file not found: {args.input}")
        print("💡 First run: python3 -m scripts.extract --input <parsed.json> --output <facts.json>")
        sys.exit(1)
    
    print(f"🔍 Validating facts from: {args.input}")
    print(f"📝 Clean facts will be saved to: {args.output}")
    if args.issues:
        print(f"📋 Issues report will be saved to: {args.issues}")
    print("-" * 60)
    
    try:
        # Load extracted facts
        import json
        with open(args.input, 'r', encoding='utf-8') as f:
            facts_data = json.load(f)
        
        # Run validation
        valid_facts, report = validate_extracted_facts(facts_data)
        
        # Print summary
        report.print_summary()
        
        # Show detailed issues if requested
        if args.show_details and report.issues:
            print(f"\n🔍 Detailed Issues:")
            print("-" * 40)
            
            # Group issues by type
            issues_by_type = {}
            for issue in report.issues:
                if issue.issue_type not in issues_by_type:
                    issues_by_type[issue.issue_type] = []
                issues_by_type[issue.issue_type].append(issue)
            
            for issue_type, issues in issues_by_type.items():
                print(f"\n📋 {issue_type.replace('_', ' ').title()}: ({len(issues)} occurrences)")
                for issue in issues[:3]:  # Show first 3 of each type
                    severity_icon = "❌" if issue.severity == "error" else "⚠️" if issue.severity == "warning" else "ℹ️"
                    print(f"   {severity_icon} Fact #{issue.fact_index}: {issue.message}")
                    if issue.suggestion:
                        print(f"      💡 {issue.suggestion}")
                if len(issues) > 3:
                    print(f"   ... and {len(issues) - 3} more")
        
        # Save results
        save_validation_results(valid_facts, report, args.output, args.issues)
        
        # Final summary
        print("-" * 60)
        if report.invalid_facts > 0:
            print(f"⚠️  Found {report.invalid_facts} invalid facts that were filtered out")
        if report.warnings > 0:
            print(f"📝 Found {report.warnings} warnings (facts kept but flagged for review)")
        
        print(f"✅ Validation complete!")
        print(f"📊 Clean dataset: {report.valid_facts}/{report.total_facts} facts ({report.valid_facts/report.total_facts*100:.1f}%)")
        
        # Show next steps
        quality_score = report.valid_facts / report.total_facts if report.total_facts > 0 else 0
        if quality_score < 0.8:
            print(f"\n🎯 Next steps:")
            print(f"   📝 Review extraction prompts - quality is {quality_score:.1%}")
            print(f"   🔍 Check issues report: {args.issues if args.issues else 'run with --issues flag'}")
        else:
            print(f"\n🎯 Next steps (ignore these for now, will updated when normalization step is complete):")
            print(f"1. Run normalization: python3 -m scripts.normalize --input {args.output}")
            print(f"2. Load into graph: python3 -m scripts.load_graph --input <normalized.json>")
    
    except KeyboardInterrupt:
        print("\n⏹ Validation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()