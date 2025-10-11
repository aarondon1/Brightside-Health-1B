"""Ontology normalization utilities.

This module loads ontology mappings from ``configs/mappings.yaml`` and uses
string normalization + fuzzy matching to ground extracted clinical facts to
canonical concept identifiers (RxNorm, SNOMED CT, etc.).

It exposes an :class:`OntologyNormalizer` class that can be reused in notebooks
or scripts and provides a small CLI when invoked as ``python -m
src.core.normalize_ontology``.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

import yaml

from src.schemas.triples import NormalizationMatch, NormalizedTriple

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class Concept:
    """A single concept entry from the ontology configuration."""

    entity_type: str
    concept_id: str
    label: str
    provider: str
    synonyms: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LookupResult:
    """Internal helper for returning matches from the lookup index."""

    concept: Concept
    match_type: str
    score: float


class NormalizationConfigError(RuntimeError):
    """Raised when the ontology configuration file is missing or invalid."""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _normalize_surface(text: str) -> str:
    """Normalize a surface string for lookup purposes."""

    text = text.strip().lower()
    text = re.sub(r"[\u2018\u2019]", "'", text)  # normalize smart quotes
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _ensure_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


# ---------------------------------------------------------------------------
# OntologyNormalizer implementation
# ---------------------------------------------------------------------------


class OntologyNormalizer:
    """Normalize extracted clinical facts to canonical ontology concepts."""

    def __init__(
        self,
        config_path: Path | str = Path("configs/mappings.yaml"),
        *,
        min_fuzzy_score: float = 0.86,
    ) -> None:
        self.config_path = Path(config_path)
        self.min_fuzzy_score = min_fuzzy_score
        self._concept_index: Dict[str, Dict[str, LookupResult]] = {}
        self._fuzzy_keys: Dict[str, List[str]] = {}
        self.providers: Dict[str, Any] = {}

        self._load_config()

    # ------------------------------------------------------------------
    # Configuration loading
    # ------------------------------------------------------------------
    def _load_config(self) -> None:
        if not self.config_path.exists():
            raise NormalizationConfigError(
                f"Ontology mapping file not found: {self.config_path}"
            )

        with self.config_path.open("r", encoding="utf-8") as fh:
            raw_cfg = yaml.safe_load(fh) or {}

        providers = raw_cfg.get("providers", {})
        if not isinstance(providers, MutableMapping):
            raise NormalizationConfigError("`providers` must be a mapping")
        self.providers = providers

        entities = raw_cfg.get("entities")
        if not isinstance(entities, MutableMapping):
            raise NormalizationConfigError("`entities` section is required in mappings.yaml")

        for entity_type, concepts in entities.items():
            if not isinstance(concepts, Iterable):
                raise NormalizationConfigError(
                    f"Concept list for '{entity_type}' must be an iterable"
                )
            self._register_concepts(entity_type, concepts)

    def _register_concepts(self, entity_type: str, concepts: Iterable[Any]) -> None:
        index: Dict[str, LookupResult] = {}
        fuzzy_keys: List[str] = []

        for entry in concepts:
            if not isinstance(entry, Mapping):
                raise NormalizationConfigError(
                    f"Each concept must be a mapping. Offending entry in '{entity_type}': {entry!r}"
                )

            concept_id = str(entry.get("id") or entry.get("concept_id"))
            label = str(entry.get("label") or entry.get("name"))
            provider = str(entry.get("provider") or entry.get("source", "custom"))
            if not concept_id or not label:
                raise NormalizationConfigError(
                    f"Concepts must include 'id' and 'label'. Offending entry in '{entity_type}': {entry!r}"
                )

            synonyms = [str(s) for s in entry.get("synonyms", []) if s]
            metadata = {
                k: v
                for k, v in entry.items()
                if k not in {"id", "concept_id", "label", "name", "provider", "source", "synonyms"}
            }

            concept = Concept(
                entity_type=entity_type,
                concept_id=concept_id,
                label=label,
                provider=provider,
                synonyms=synonyms,
                metadata=metadata,
            )

            # Register preferred label
            canonical_key = _normalize_surface(label)
            if canonical_key:
                index[canonical_key] = LookupResult(concept, "exact", 1.0)
                fuzzy_keys.append(canonical_key)

            # Register synonyms
            for synonym in synonyms:
                synonym_key = _normalize_surface(synonym)
                if synonym_key and synonym_key not in index:
                    index[synonym_key] = LookupResult(concept, "synonym", 1.0)
                    fuzzy_keys.append(synonym_key)

        self._concept_index[entity_type] = index
        self._fuzzy_keys[entity_type] = sorted(set(fuzzy_keys))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def normalize_fact(self, fact: Mapping[str, Any]) -> NormalizedTriple:
        """Normalize a single fact dictionary."""

        def make_match(entity_type: str, value: Optional[str]) -> NormalizationMatch:
            if value is None or str(value).strip() == "":
                return NormalizationMatch(text=value or "", match_type="unmatched", score=0.0)
            return self._lookup(entity_type, str(value))

        drug = make_match("drugs", fact.get("drug_name"))
        condition = make_match("conditions", fact.get("condition_name"))
        relation = make_match("relations", fact.get("relation"))

        outcome_value = fact.get("outcome")
        outcome = None
        if outcome_value not in (None, ""):
            outcome = make_match("outcomes", str(outcome_value))

        side_effect_matches = [
            make_match("side_effects", side_effect)
            for side_effect in _ensure_list(fact.get("side_effects"))
        ]

        return NormalizedTriple(
            raw_fact=dict(fact),
            drug=drug,
            condition=condition,
            relation=relation,
            outcome=outcome,
            side_effects=side_effect_matches,
            effect_size=fact.get("effect_size"),
            confidence_interval=fact.get("confidence_interval"),
        )

    def normalize(self, facts: Iterable[Mapping[str, Any]]) -> List[NormalizedTriple]:
        return [self.normalize_fact(fact) for fact in facts]

    def normalize_file(self, input_path: Path | str) -> List[NormalizedTriple]:
        facts = self._load_facts(Path(input_path))
        return self.normalize(facts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _lookup(self, entity_type: str, value: str) -> NormalizationMatch:
        lookup_table = self._concept_index.get(entity_type, {})
        normalized_value = _normalize_surface(value)

        if not normalized_value:
            return NormalizationMatch(text=value, match_type="unmatched", score=0.0)

        result = lookup_table.get(normalized_value)
        if result:
            return NormalizationMatch(
                text=value,
                concept_id=result.concept.concept_id,
                label=result.concept.label,
                provider=result.concept.provider,
                match_type=result.match_type,
                score=result.score,
            )

        # Fuzzy match against known keys
        fuzzy_candidates = difflib.get_close_matches(
            normalized_value,
            self._fuzzy_keys.get(entity_type, []),
            n=1,
            cutoff=self.min_fuzzy_score,
        )

        if fuzzy_candidates:
            candidate_key = fuzzy_candidates[0]
            result = lookup_table[candidate_key]
            ratio = difflib.SequenceMatcher(None, normalized_value, candidate_key).ratio()
            return NormalizationMatch(
                text=value,
                concept_id=result.concept.concept_id,
                label=result.concept.label,
                provider=result.concept.provider,
                match_type="fuzzy",
                score=ratio,
            )

        return NormalizationMatch(text=value, match_type="unmatched", score=0.0)

    def _load_facts(self, path: Path) -> List[Mapping[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if isinstance(data, list):
            return [dict(item) for item in data]
        if isinstance(data, Mapping):
            # Support multiple common wrapper keys produced by earlier pipeline stages
            # in addition to the raw list or the 'triples' key used by extraction.
            for key in ("triples", "validated_facts", "extracted_facts"):
                if key in data and isinstance(data[key], list):
                    return [dict(item) for item in data[key]]
            raise ValueError(
                "Expected a list under one of keys: 'triples', 'validated_facts', or 'extracted_facts'"
            )

        raise ValueError(
            "Input JSON must be a list of facts or an object containing 'triples', 'validated_facts', or 'extracted_facts'"
        )

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def summarize(normalized: Iterable[NormalizedTriple]) -> Dict[str, Any]:
        totals = {
            "total": 0,
            "drug": {"matched": 0, "unmatched": 0},
            "condition": {"matched": 0, "unmatched": 0},
            "relation": {"matched": 0, "unmatched": 0},
            "outcome": {"matched": 0, "unmatched": 0},
            "side_effects": {"matched": 0, "unmatched": 0},
        }

        for fact in normalized:
            totals["total"] += 1
            totals["drug"]["matched" if fact.drug.is_matched() else "unmatched"] += 1
            totals["condition"][
                "matched" if fact.condition.is_matched() else "unmatched"
            ] += 1
            totals["relation"][
                "matched" if fact.relation.is_matched() else "unmatched"
            ] += 1
            if fact.outcome is None:
                totals["outcome"]["matched"] += 1
            else:
                totals["outcome"][
                    "matched" if fact.outcome.is_matched() else "unmatched"
                ] += 1

            if not fact.side_effects:
                totals["side_effects"]["matched"] += 1
            else:
                if all(se.is_matched() for se in fact.side_effects):
                    totals["side_effects"]["matched"] += 1
                else:
                    totals["side_effects"]["unmatched"] += 1

        return totals


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize clinical triples")
    parser.add_argument("--input", required=True, help="Path to extracted facts JSON")
    parser.add_argument(
        "--output",
        help="Path to write normalized JSON (defaults to <input>_normalized.json)",
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
        help="Minimum similarity threshold for fuzzy matching (default: 0.86)",
    )

    args = parser.parse_args(argv)

    normalizer = OntologyNormalizer(
        args.config,
        min_fuzzy_score=args.min_fuzzy_score,
    )

    normalized = normalizer.normalize_file(args.input)
    summary = OntologyNormalizer.summarize(normalized)

    if args.output:
        resolved_output = Path(args.output)
    else:
        resolved_output = Path(args.input).with_name(
            f"{Path(args.input).stem}_normalized.json"
        )

    with resolved_output.open("w", encoding="utf-8") as fh:
        json.dump([fact.model_dump() for fact in normalized], fh, indent=2, ensure_ascii=False)

    print("Normalization summary:")
    for key, value in summary.items():
        if key == "total":
            print(f"  Total facts: {value}")
        else:
            print(
                f"  {key.title()}: matched={value['matched']} unmatched={value['unmatched']}"
            )

    print(f"Normalized output written to: {resolved_output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual CLI invocation
    raise SystemExit(_cli())
