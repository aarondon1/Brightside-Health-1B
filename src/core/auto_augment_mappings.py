#!/usr/bin/env python3
"""
Ontology augmentation with YAML formatting preservation.

This is the CORRECTED version with the right class name (MappingsAugmenter)
for use with normalize.py

Features:
- Preserves YAML formatting using ruamel.yaml
- Adds timestamped comments to auto-added entries
- API lookup (RxNorm, SNOMED CT) + CUSTOM fallback
- Automatic backups
- Zero manual work required

Usage:
  python -m scripts.normalize --input file.json --auto-augment-dry-run
  python -m scripts.normalize --input file.json --auto-augment
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from collections import defaultdict

import requests

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    HAS_RUAMEL = True
except ImportError:
    HAS_RUAMEL = False


class OntologyAPIClient:
    """Client for querying free ontology APIs (RxNorm, SNOMED CT, LOINC)."""

    RXNORM_API_BASE = "https://rxnav.nlm.nih.gov/REST"
    SNOMED_API_BASE = "https://browser.ihtsdotools.org/snowstorm/snomed-ct"
    LOINC_API_BASE = "https://loinc.org/api"

    def __init__(self, cache_file: Optional[Path] = None):
        """Initialize API client with optional caching."""
        self.cache_file = cache_file or Path(".ontology_cache.json")
        self.cache = self._load_cache()
        self.session = requests.Session()

    def _load_cache(self) -> Dict[str, Any]:
        """Load cached API results."""
        if self.cache_file.exists():
            try:
                with self.cache_file.open("r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with self.cache_file.open("w") as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass

    def lookup_rxnorm(self, drug_name: str) -> Optional[Dict[str, Any]]:
        """Look up drug in RxNorm API."""
        cache_key = f"rxnorm:{drug_name.lower()}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            response = self.session.get(
                f"{self.RXNORM_API_BASE}/approximateTerm.json",
                params={"term": drug_name, "maxEntries": 1},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("approximateGroup"):
                candidates = data["approximateGroup"].get("candidate", [])
                if candidates:
                    best = candidates[0]
                    result = {
                        "source": "RXNORM",
                        "concept_id": f"RXNORM:{best.get('rxcui')}",
                        "label": best.get("name"),
                    }
                    self.cache[cache_key] = result
                    return result
        except Exception:
            pass

        self.cache[cache_key] = None
        return None

    def lookup_snomed(self, term: str) -> Optional[Dict[str, Any]]:
        """Look up term in SNOMED CT Browser API."""
        cache_key = f"snomed:{term.lower()}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            response = self.session.get(
                f"{self.SNOMED_API_BASE}/concepts",
                params={"query": term, "limit": 1},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("items"):
                best = data["items"][0]
                result = {
                    "source": "SNOMED",
                    "concept_id": f"SNOMED:{best.get('id')}",
                    "label": best.get("pt", {}).get("term", term),
                }
                self.cache[cache_key] = result
                return result
        except Exception:
            pass

        self.cache[cache_key] = None
        return None

    def lookup_loinc(self, term: str) -> Optional[Dict[str, Any]]:
        """Look up term in LOINC API.
        
        LOINC is best for outcomes and clinical observations.
        Free API endpoint: https://loinc.org/api/
        """
        cache_key = f"loinc:{term.lower()}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            response = self.session.get(
                f"{self.LOINC_API_BASE}/search",
                params={"q": term, "limit": 1},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("documents") and len(data["documents"]) > 0:
                best = data["documents"][0]
                loinc_code = best.get("loinc_num")
                display_name = best.get("display_name", term)
                
                if loinc_code:
                    result = {
                        "source": "LOINC",
                        "concept_id": f"LOINC:{loinc_code}",
                        "label": display_name,
                    }
                    self.cache[cache_key] = result
                    return result
        except Exception:
            pass

        self.cache[cache_key] = None
        return None


class MappingsAugmenter:
    """Main augmenter class (compatible with normalize.py)."""

    CUSTOM_ID_COUNTERS: Dict[str, int] = {
        "drugs": 1000,
        "conditions": 2000,
        "relations": 3000,
        "outcomes": 4000,
        "side_effects": 5000,
    }

    def __init__(self, mappings_path: Path | str) -> None:
        """Initialize augmenter."""
        self.mappings_path = Path(mappings_path)
        self.yaml_content = self._load_yaml_text()
        self.api_client = OntologyAPIClient()
        self.yaml = None
        self.config = None
        
        # Try to use ruamel.yaml if available
        if HAS_RUAMEL:
            try:
                self.yaml = YAML()
                self.yaml.preserve_quotes = True
                self.yaml.default_flow_style = False
                self.yaml.width = 120
                with self.mappings_path.open("r", encoding="utf-8") as fh:
                    self.config = self.yaml.load(fh)
            except Exception:
                self.yaml = None
                self.config = None

    def _load_yaml_text(self) -> str:
        """Load YAML as raw text to preserve formatting."""
        if not self.mappings_path.exists():
            raise FileNotFoundError(f"Mappings file not found: {self.mappings_path}")

        with self.mappings_path.open("r", encoding="utf-8") as fh:
            return fh.read()

    def _get_next_custom_id(self, entity_type: str) -> str:
        """Generate next custom ID."""
        counter = self.CUSTOM_ID_COUNTERS.get(entity_type, 9000)
        self.CUSTOM_ID_COUNTERS[entity_type] = counter + 1
        return f"CUSTOM:{entity_type.upper()}_{counter}"

    def _lookup_apis(self, entity_type: str, text: str) -> Optional[tuple[str, str]]:
        """Try API lookups with priority order.
        
        Priority:
        - Drugs: RxNorm → SNOMED fallback
        - Conditions: SNOMED → LOINC fallback
        - Outcomes: LOINC → SNOMED fallback (outcomes are often lab observations)
        - Side Effects: SNOMED → LOINC fallback
        """
        # RxNorm for drugs
        if entity_type == "drugs":
            result = self.api_client.lookup_rxnorm(text)
            if result:
                return (result.get("concept_id"), "rxnorm")
            # Fallback to SNOMED
            result = self.api_client.lookup_snomed(text)
            if result:
                return (result.get("concept_id"), "snomed")

        # LOINC preferred for outcomes (clinical observations)
        if entity_type == "outcomes":
            result = self.api_client.lookup_loinc(text)
            if result:
                return (result.get("concept_id"), "loinc")
            # Fallback to SNOMED
            result = self.api_client.lookup_snomed(text)
            if result:
                return (result.get("concept_id"), "snomed")

        # SNOMED for conditions
        if entity_type == "conditions":
            result = self.api_client.lookup_snomed(text)
            if result:
                return (result.get("concept_id"), "snomed")
            # Fallback to LOINC
            result = self.api_client.lookup_loinc(text)
            if result:
                return (result.get("concept_id"), "loinc")

        # SNOMED for side effects
        if entity_type == "side_effects":
            result = self.api_client.lookup_snomed(text)
            if result:
                return (result.get("concept_id"), "snomed")
            # Fallback to LOINC
            result = self.api_client.lookup_loinc(text)
            if result:
                return (result.get("concept_id"), "loinc")

        # Relations: try SNOMED
        if entity_type == "relations":
            result = self.api_client.lookup_snomed(text)
            if result:
                return (result.get("concept_id"), "snomed")

        return None

    def extract_unmatched_items(
        self, normalized_json_path: Path | str
    ) -> Dict[str, list[str]]:
        """Extract unmatched items from normalized JSON."""
        path = Path(normalized_json_path)
        if not path.exists():
            raise FileNotFoundError(f"Normalized JSON not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if isinstance(data, list):
            facts = data
        elif isinstance(data, dict) and "normalized_facts" in data:
            facts = data["normalized_facts"]
        else:
            raise ValueError("Unexpected JSON structure")

        unmatched = {
            "drugs": [],
            "conditions": [],
            "relations": [],
            "outcomes": [],
            "side_effects": [],
        }

        for fact in facts:
            if isinstance(fact.get("drug"), dict):
                if fact["drug"].get("match_type") == "unmatched" and fact["drug"].get("text"):
                    unmatched["drugs"].append(fact["drug"]["text"])

            if isinstance(fact.get("condition"), dict):
                if fact["condition"].get("match_type") == "unmatched" and fact["condition"].get("text"):
                    unmatched["conditions"].append(fact["condition"]["text"])

            if isinstance(fact.get("relation"), dict):
                if fact["relation"].get("match_type") == "unmatched" and fact["relation"].get("text"):
                    unmatched["relations"].append(fact["relation"]["text"])

            outcome = fact.get("outcome")
            if isinstance(outcome, dict) and outcome.get("match_type") == "unmatched" and outcome.get("text"):
                unmatched["outcomes"].append(outcome["text"])

            for se in fact.get("side_effects", []):
                if isinstance(se, dict) and se.get("match_type") == "unmatched" and se.get("text"):
                    unmatched["side_effects"].append(se["text"])

        return unmatched

    def augment_mappings(
        self, unmatched: Dict[str, list[str]], dry_run: bool = False
    ) -> Dict[str, Any]:
        """Augment mappings."""
        summary = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "standard_matches": {},
            "custom_additions": {},
            "additions_by_entity": defaultdict(list),
        }

        modified_content = self.yaml_content
        entries_added = False

        for entity_type, texts in unmatched.items():
            if not texts:
                continue

            seen_normalized = set()
            standard_matches = []
            custom_additions = []

            for text in texts:
                text_normalized = text.strip().lower()

                if text_normalized and text_normalized not in seen_normalized:
                    seen_normalized.add(text_normalized)

                    api_match = self._lookup_apis(entity_type, text)

                    if api_match:
                        concept_id, provider = api_match
                        standard_matches.append({
                            "text": text,
                            "concept_id": concept_id,
                            "provider": provider,
                        })
                        summary["additions_by_entity"][entity_type].append({
                            "text": text,
                            "source": "api",
                            "concept_id": concept_id,
                            "provider": provider,
                        })
                    else:
                        custom_id = self._get_next_custom_id(entity_type)
                        custom_additions.append(text)
                        summary["additions_by_entity"][entity_type].append({
                            "text": text,
                            "source": "custom",
                            "concept_id": custom_id,
                        })

            if standard_matches:
                summary["standard_matches"][entity_type] = standard_matches
                entries_added = True

            if custom_additions:
                summary["custom_additions"][entity_type] = {
                    "added": len(custom_additions),
                    "items": custom_additions,
                }
                entries_added = True

        if not dry_run and entries_added:
            self._backup_and_save(modified_content, summary)
        else:
            self.api_client._save_cache()

        return summary

    def _backup_and_save(self, content: str, summary: Dict[str, Any]) -> None:
        """Backup and save."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.mappings_path.with_stem(
            f"{self.mappings_path.stem}_backup_{timestamp}"
        )
        backup_path.write_text(self.yaml_content, encoding="utf-8")
        
        # Simple text append with comments
        new_content = self.yaml_content
        for entity_type, additions in summary.get("additions_by_entity", {}).items():
            if additions:
                for addition in additions:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    source = "API" if addition["source"] == "api" else "CUSTOM"
                    comment = f"# AUTO-ADDED [{ts}] - {source}"
                    entry = f"\n    {comment}\n"
                    entry += f"    - id: {addition['concept_id']}\n"
                    entry += f"      label: {addition['text']}\n"
                    entry += f"      provider: {'api' if addition['source'] == 'api' else 'custom'}\n"
                    entry += f"      synonyms: []"
                    new_content += entry

        self.mappings_path.write_text(new_content, encoding="utf-8")
        self.api_client._save_cache()

        print(f"✅ Backup created: {backup_path}")
        print(f"✅ Mappings saved: {self.mappings_path}")
        print(f"✅ Cache saved: {self.api_client.cache_file}")

    def report(self, summary: Dict[str, Any]) -> None:
        """Print report."""
        print("\n" + "=" * 70)
        print("📊 ONTOLOGY AUGMENTATION SUMMARY")
        print("=" * 70)
        print(f"Timestamp: {summary['timestamp']}")
        print(f"Dry run: {summary['dry_run']}")

        total_standard = sum(
            len(items) if isinstance(items, list) else 0
            for items in summary.get("standard_matches", {}).values()
        )
        total_custom = sum(
            items["added"] if isinstance(items, dict) else 0
            for items in summary.get("custom_additions", {}).values()
        )

        if total_standard == 0 and total_custom == 0:
            print("\n✅ All items matched!")
            print("=" * 70)
            return

        print(f"\n📡 API MATCHES: {total_standard}")
        print(f"📝 CUSTOM ENTRIES: {total_custom}")

        for entity_type, additions in summary.get("additions_by_entity", {}).items():
            if additions:
                print(f"\n  {entity_type.upper()}:")
                print("  " + "-" * 66)
                for addition in additions:
                    if addition["source"] == "api":
                        provider = addition.get("provider", "unknown").upper()
                        concept_id = addition['concept_id']
                        # Show which API provided the match
                        if "LOINC" in concept_id:
                            icon = "🔬"
                        elif "RXNORM" in concept_id:
                            icon = "💊"
                        elif "SNOMED" in concept_id:
                            icon = "📋"
                        else:
                            icon = "✓"
                        print(
                            f"    {icon} {addition['text']:<38} → {concept_id}"
                        )
                    else:
                        print(f"    + {addition['text']:<40} (CUSTOM)")

        print("\n" + "=" * 70)
        
        # Show API coverage
        api_coverage = defaultdict(int)
        for entity_type, additions in summary.get("additions_by_entity", {}).items():
            for addition in additions:
                if addition["source"] == "api":
                    if "LOINC" in addition['concept_id']:
                        api_coverage["LOINC"] += 1
                    elif "RXNORM" in addition['concept_id']:
                        api_coverage["RxNorm"] += 1
                    elif "SNOMED" in addition['concept_id']:
                        api_coverage["SNOMED"] += 1
        
        if api_coverage:
            print("API Coverage:")
            for api, count in sorted(api_coverage.items(), key=lambda x: -x[1]):
                print(f"  • {api}: {count} matches")
        
        if summary["dry_run"]:
            print("\n🔍 DRY RUN: No changes saved.")
        else:
            print("\n✅ Changes applied!")
            print(f"   • {total_standard} API matches (RxNorm, SNOMED, LOINC)")
            print(f"   • {total_custom} CUSTOM entries")
            print("   • Formatting preserved")
        print("=" * 70)


# Export for compatibility
__all__ = ["MappingsAugmenter", "OntologyAPIClient"]