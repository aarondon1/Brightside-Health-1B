"""CLI wrapper for ontology normalization with automatic mapping augmentation."""
# python -m scripts.normalize --input data/processed/validated/<paper>_validated.json --auto-augment

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.normalize_ontology import OntologyNormalizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize extracted clinical facts")
    parser.add_argument("--input", required=True, help="Path to validated facts JSON")
    parser.add_argument(
        "--output",
        help="Where to write normalized JSON (default: data/processed/normalized/{stem}_normalized.json)",
    )
    parser.add_argument(
        "--config",
        default="configs/mappings.yaml",
        help="Ontology mapping YAML (default: configs/mappings.yaml)",
    )
    parser.add_argument(
        "--min-fuzzy-score",
        type=float,
        default=0.86,
        help="Minimum similarity threshold (default: 0.86)",
    )
    parser.add_argument(
        "--auto-augment",
        action="store_true",
        help="Automatically add unmatched items to mappings.yaml",
    )
    parser.add_argument(
        "--auto-augment-dry-run",
        action="store_true",
        help="Preview auto-augmentation without saving (implies --auto-augment)",
    )

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    output_path = (
        Path(args.output)
        if args.output
        else (Path("data/processed/normalized") / f"{input_path.stem}_normalized.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Normalize facts
    print("\n" + "=" * 70)
    print("📌 STEP 1: Normalizing facts against mappings...")
    print("=" * 70)

    normalizer = OntologyNormalizer(
        config_path=args.config, min_fuzzy_score=args.min_fuzzy_score
    )
    normalized = normalizer.normalize_file(input_path)
    summary = OntologyNormalizer.summarize(normalized)

    payload = {"normalized_facts": [fact.model_dump() for fact in normalized]}
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("Normalization summary:")
    print(f"  Total facts: {summary['total']}")
    for field in ["drug", "condition", "relation", "outcome", "side_effects"]:
        stats = summary[field]
        print(
            f"  {field.replace('_', ' ').title()}: matched={stats['matched']} unmatched={stats['unmatched']}"
        )
    print(f"\nNormalized facts saved to: {output_path}")

    # Step 2: Auto-augment if requested
    if args.auto_augment or args.auto_augment_dry_run:
        print("\n" + "=" * 70)
        print("📌 STEP 2: Auto-augmenting mappings...")
        print("=" * 70)

        # Import here to avoid dependency if not used
        try:
            from src.core.auto_augment_mappings import MappingsAugmenter
        except ImportError:
            print("❌ Error: Could not import auto_augment_mappings module")
            print("Make sure auto_augment_mappings.py is in src/core/")
            return 1

        try:
            augmenter = MappingsAugmenter(args.config)
            unmatched = augmenter.extract_unmatched_items(output_path)

            # Count unmatched items
            total_unmatched = sum(len(items) for items in unmatched.values())

            if total_unmatched == 0:
                print("✅ All items matched - no augmentation needed!")
            else:
                print(f"📋 Found {total_unmatched} unmatched items")
                for entity_type, items in unmatched.items():
                    if items:
                        print(f"   • {entity_type}: {len(items)} unique unmatched items")

                # Perform augmentation
                dry_run = args.auto_augment_dry_run
                aug_summary = augmenter.augment_mappings(unmatched, dry_run=dry_run)
                augmenter.report(aug_summary)

                if dry_run:
                    print(
                        "\n💡 TIP: Run again without --auto-augment-dry-run to apply changes"
                    )
                else:
                    print("\n💡 NEXT STEP: Re-run normalization to match new concepts")
                    print(
                        f"   python -m scripts.normalize --input {args.input} --config {args.config}"
                    )

        except Exception as e:
            print(f"❌ Auto-augmentation error: {e}")
            import traceback

            traceback.print_exc()
            return 1
    else:
        print("\n" + "=" * 70)
        print("💡 OPTIONAL NEXT STEPS:")
        print("=" * 70)
        print("• Auto-augment mappings and re-normalize:")
        print(
            f"   python -m scripts.normalize --input {args.input} --config {args.config} --auto-augment"
        )
        print("• Preview augmentation without saving:")
        print(
            f"   python -m scripts.normalize --input {args.input} --config {args.config} --auto-augment-dry-run"
        )
        print("• Show unmatched items manually:")
        print(f"   python -m scripts.show_unmatched_normalized --input {output_path}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())