#!/usr/bin/env python3
"""
Automatically augment mappings.yaml with unmatched items.

This script:
1. Reads normalized JSON with unmatched items
2. Generates new concept entries for each unmatched item
3. Adds them to mappings.yaml with CUSTOM provider IDs
4. Backs up the original mappings.yaml

Usage:
  python auto_augment_mappings.py \
    --input data/processed/normalized/sample_normalized.json \
    --mappings configs/mappings.yaml \
    --dry-run  # Optional: preview changes without saving

"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

import yaml


class MappingsAugmenter:
    """Automatically augment ontology mappings with unmatched items."""

    # Counter for generating unique custom IDs
    CUSTOM_ID_COUNTERS: Dict[str, int] = {
        "drugs": 1000,
        "conditions": 2000,
        "relations": 3000,
        "outcomes": 4000,
        "side_effects": 5000,
    }

    def __init__(self, mappings_path: Path | str) -> None:
        """Initialize with path to existing mappings.yaml."""
        self.mappings_path = Path(mappings_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load existing mappings.yaml config."""
        if not self.mappings_path.exists():
            raise FileNotFoundError(f"Mappings file not found: {self.mappings_path}")

        with self.mappings_path.open("r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}

        if "entities" not in config:
            config["entities"] = {}

        for entity_type in ["drugs", "conditions", "relations", "outcomes", "side_effects"]:
            if entity_type not in config["entities"]:
                config["entities"][entity_type] = []

        return config

    def _get_next_custom_id(self, entity_type: str) -> str:
        """Generate next custom ID for entity type."""
        counter = self.CUSTOM_ID_COUNTERS.get(entity_type, 9000)
        self.CUSTOM_ID_COUNTERS[entity_type] = counter + 1
        return f"CUSTOM:{entity_type.upper()}_{counter}"

    def _existing_labels_normalized(self, entity_type: str) -> set[str]:
        """Get normalized versions of all existing labels for deduplication."""
        existing = set()
        for concept in self.config["entities"].get(entity_type, []):
            label = str(concept.get("label", "")).strip().lower()
            if label:
                existing.add(label)
        return existing

    def extract_unmatched_items(self, normalized_json_path: Path | str) -> Dict[str, List[str]]:
        """
        Extract unmatched items from normalized JSON.

        Returns:
            Dict mapping entity_type -> list of unmatched text values
        """
        path = Path(normalized_json_path)
        if not path.exists():
            raise FileNotFoundError(f"Normalized JSON not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Handle different JSON structures
        if isinstance(data, list):
            facts = data
        elif isinstance(data, dict) and "normalized_facts" in data:
            facts = data["normalized_facts"]
        else:
            raise ValueError(
                "Expected normalized JSON to be a list or have 'normalized_facts' key"
            )

        unmatched = {
            "drugs": [],
            "conditions": [],
            "relations": [],
            "outcomes": [],
            "side_effects": [],
        }

        for fact in facts:
            # Check drug
            if isinstance(fact.get("drug"), dict):
                if fact["drug"].get("match_type") == "unmatched" and fact["drug"].get("text"):
                    unmatched["drugs"].append(fact["drug"]["text"])

            # Check condition
            if isinstance(fact.get("condition"), dict):
                if (
                    fact["condition"].get("match_type") == "unmatched"
                    and fact["condition"].get("text")
                ):
                    unmatched["conditions"].append(fact["condition"]["text"])

            # Check relation
            if isinstance(fact.get("relation"), dict):
                if (
                    fact["relation"].get("match_type") == "unmatched"
                    and fact["relation"].get("text")
                ):
                    unmatched["relations"].append(fact["relation"]["text"])

            # Check outcome
            outcome = fact.get("outcome")
            if isinstance(outcome, dict) and outcome.get("match_type") == "unmatched" and outcome.get("text"):
                unmatched["outcomes"].append(outcome["text"])

            # Check side effects
            for se in fact.get("side_effects", []):
                if isinstance(se, dict) and se.get("match_type") == "unmatched" and se.get("text"):
                    unmatched["side_effects"].append(se["text"])

        return unmatched

    def _create_concept_entry(self, entity_type: str, text: str) -> Dict[str, Any]:
        """Create a concept entry for an unmatched item."""
        return {
            "id": self._get_next_custom_id(entity_type),
            "label": text,
            "provider": "custom",
            "synonyms": [],
        }

    def augment_mappings(self, unmatched: Dict[str, List[str]], dry_run: bool = False) -> Dict[str, Any]:
        """
        Augment mappings with new concepts.

        Args:
            unmatched: Dict mapping entity_type -> list of unmatched text values
            dry_run: If True, don't modify the file

        Returns:
            Summary of changes made
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "changes": {},
        }

        for entity_type, texts in unmatched.items():
            if not texts:
                continue

            # Deduplicate and filter out items that already exist
            existing_labels = self._existing_labels_normalized(entity_type)
            unique_texts = []
            seen_normalized = set()  # Track items we're adding in THIS batch

            for text in texts:
                text_normalized = text.strip().lower()
                # Skip if empty, already exists, or we're adding it in this batch
                if text_normalized and text_normalized not in existing_labels and text_normalized not in seen_normalized:
                    unique_texts.append(text)
                    seen_normalized.add(text_normalized)

            if not unique_texts:
                continue

            # Create new concept entries
            new_concepts = [self._create_concept_entry(entity_type, text) for text in unique_texts]

            # Add to config
            self.config["entities"][entity_type].extend(new_concepts)

            summary["changes"][entity_type] = {
                "added": len(new_concepts),
                "items": [concept["label"] for concept in new_concepts],
            }

        if not dry_run and summary["changes"]:
            self._backup_and_save()

        return summary

    def _backup_and_save(self) -> None:
        """Backup original and save updated mappings."""
        # Create backup
        backup_path = self.mappings_path.with_stem(
            f"{self.mappings_path.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        backup_path.write_text(self.mappings_path.read_text(encoding="utf-8"), encoding="utf-8")

        # Save updated config
        with self.mappings_path.open("w", encoding="utf-8") as fh:
            yaml.dump(
                self.config,
                fh,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )

        print(f"✅ Backup created: {backup_path}")
        print(f"✅ Mappings saved: {self.mappings_path}")

    def report(self, summary: Dict[str, Any]) -> None:
        """Print summary of changes."""
        print("\n" + "=" * 70)
        print("📊 ONTOLOGY AUGMENTATION SUMMARY")
        print("=" * 70)
        print(f"Timestamp: {summary['timestamp']}")
        print(f"Dry run: {summary['dry_run']}")

        if not summary["changes"]:
            print("\n✅ No new items to add - all items already in mappings!")
            print("=" * 70)
            return

        total_added = sum(change["added"] for change in summary["changes"].values())
        print(f"\n📈 Total new concepts added: {total_added}")

        for entity_type, change in summary["changes"].items():
            print(f"\n  {entity_type.upper()} ({change['added']} new):")
            print("  " + "-" * 66)
            for item in change["items"]:
                print(f"    • {item}")

        print("\n" + "=" * 70)
        if summary["dry_run"]:
            print("🔍 DRY RUN: No changes were saved. Run without --dry-run to apply.")
        else:
            print("✅ Changes applied successfully!")
        print("=" * 70)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Automatically augment mappings.yaml with unmatched items",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without saving
  python auto_augment_mappings.py --input normalized.json --mappings configs/mappings.yaml --dry-run

  # Apply changes
  python auto_augment_mappings.py --input normalized.json --mappings configs/mappings.yaml

  # Use custom mapping file
  python auto_augment_mappings.py --input data/normalized.json --mappings custom_mappings.yaml
        """,
    )

    parser.add_argument("--input", required=True, help="Path to normalized JSON file")
    parser.add_argument(
        "--mappings",
        default="configs/mappings.yaml",
        help="Path to mappings.yaml (default: configs/mappings.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )

    args = parser.parse_args(argv)

    try:
        input_path = Path(args.input)
        mappings_path = Path(args.mappings)

        print("\n" + "=" * 70)
        print("🔍 ONTOLOGY AUTO-AUGMENTATION")
        print("=" * 70)
        print(f"Input: {input_path}")
        print(f"Mappings: {mappings_path}")
        print(f"Dry run: {args.dry_run}")

        augmenter = MappingsAugmenter(mappings_path)
        unmatched = augmenter.extract_unmatched_items(input_path)

        # Count unmatched items
        total_unmatched = sum(len(items) for items in unmatched.values())
        print(f"\n📋 Found {total_unmatched} unmatched items across entity types")
        for entity_type, items in unmatched.items():
            if items:
                print(f"   • {entity_type}: {len(items)} unmatched")

        summary = augmenter.augment_mappings(unmatched, dry_run=args.dry_run)
        augmenter.report(summary)

        return 0

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())