#!/usr/bin/env python3
"""
Validate extracted clinical facts for quality and consistency.
"""
import argparse
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.validate import validate_extracted_facts, save_validation_results

def main():
    parser = argparse.ArgumentParser(description="Validate extracted clinical facts")
    parser.add_argument("--input", required=True, help="Path to extracted facts JSON file")
    parser.add_argument("--output", help="Path for validated facts output (default: data/processed/validated/{stem}_validated.json)")
    parser.add_argument("--issues", help="Path to save detailed validation issues report")
    parser.add_argument("--show-details", action="store_true", help="Show detailed validation issues")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"❌ Input file not found: {args.input}")
        print("💡 First run extract: python -m scripts.extract --input <parsed.json>")
        sys.exit(1)

    if not args.output:
        out_dir = Path("data/processed/validated")
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output = out_dir / f"{in_path.stem}_validated.json"

    if args.show_details and not args.issues:
        out_path = Path(args.output)
        args.issues = out_path.parent / f"{out_path.stem}_issues.json"

    print(f"🔍 Validating: {in_path}")
    print(f"📝 Clean facts → {args.output}")
    if args.issues:
        print(f"📋 Issues → {args.issues}")
    print("-" * 60)

    try:
        import json
        facts_data = json.loads(in_path.read_text(encoding="utf-8"))
        valid_facts, report = validate_extracted_facts(facts_data)
        report.print_summary()

        if args.show_details and report.issues:
            print(f"\n🔍 Detailed Issues (showing a sample):")
            print("-" * 40)
            issues_by_type = {}
            for issue in report.issues:
                issues_by_type.setdefault(issue.issue_type, []).append(issue)
            for issue_type, issues in issues_by_type.items():
                print(f"\n📋 {issue_type.replace('_', ' ').title()}: ({len(issues)} occurrences)")
                for issue in issues[:3]:
                    icon = "❌" if issue.severity == "error" else "⚠️" if issue.severity == "warning" else "ℹ️"
                    print(f"   {icon} Fact #{issue.fact_index}: {issue.message}")

        save_validation_results(valid_facts, report, args.output, args.issues)

        print("-" * 60)
        print("✅ Validation complete!")
        if report.total_facts:
            pct = report.valid_facts / report.total_facts * 100
            print(f"📊 Clean dataset: {report.valid_facts}/{report.total_facts} ({pct:.1f}%)")

        print("\nNext:")
        print(f"  python -m scripts.auto_validate_quality --input \"{args.output}\"")
        print(f"  python -m scripts.normalize --input \"{args.output}\"")
    except KeyboardInterrupt:
        print("\n⏹ Validation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()