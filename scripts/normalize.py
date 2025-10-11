"""CLI wrapper for ontology normalization."""
# run this: 
# python -m scripts.normalize --input data/processed/validated/sample_extracted_validated.json 
# --output data/processed/normalized/sample_normalized.json 
# --config configs/mappings.yaml 
# --min-fuzzy-score 0.82

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
    parser.add_argument("--input", required=True, help="Path to extracted facts JSON")
    parser.add_argument(
        "--output",
        help="Where to write normalized JSON (defaults to data/processed/normalized)",
    )
    parser.add_argument(
        "--config",
        default="configs/mappings.yaml",
        help="Ontology mapping YAML file (default: configs/mappings.yaml)",
    )
    parser.add_argument(
        "--min-fuzzy-score",
        type=float,
        default=0.86,
        help="Minimum similarity threshold for fuzzy matching (default: 0.86)",
    )

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    if args.output:
        output_path = Path(args.output)
    else:
        default_dir = Path("data/processed/normalized")
        default_dir.mkdir(parents=True, exist_ok=True)
        output_path = default_dir / f"{input_path.stem}_normalized.json"

    normalizer = OntologyNormalizer(
        config_path=args.config,
        min_fuzzy_score=args.min_fuzzy_score,
    )

    normalized = normalizer.normalize_file(input_path)
    summary = OntologyNormalizer.summarize(normalized)

    payload = {"normalized_facts": [fact.model_dump() for fact in normalized]}
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


    print("Normalization summary:")
    print(f"  Total facts: {summary['total']}")
    for field in ["drug", "condition", "relation", "outcome", "side_effects"]:
        stats = summary[field]
        print(
            f"  {field.replace('_', ' ').title()}: matched={stats['matched']} unmatched={stats['unmatched']}"
        )

    print(f"Normalized facts saved to: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())