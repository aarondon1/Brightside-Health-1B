"""Pydantic schemas shared across extraction, validation, and normalization stages."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Triple(BaseModel):
    """Structure produced by the extraction phase."""

    drug_name: str = Field(..., description="Name of the drug/medication")
    condition_name: str = Field(..., description="Medical condition being treated")
    relation: str = Field(..., description="Type of relationship (TREATS, IMPROVES, etc.)")
    outcome: Optional[str] = Field(
        None, description="Specific outcome measure if mentioned"
    )
    side_effects: List[str] = Field(
        default_factory=list, description="List of side effects mentioned"
    )
    effect_size: Optional[str] = Field(
        None, description="Effect size, percentage, or numeric result if mentioned"
    )
    confidence_interval: Optional[str] = Field(
        None, description="Confidence interval if provided"
    )
    source_id: str = Field(..., description="Document source identifier")
    section: str = Field(..., description="Section where this fact was found")
    span: str = Field(..., description="Exact text span that supports this fact")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Extractor confidence score between 0 and 1"
    )


class NormalizationMatch(BaseModel):
    """Represents a single ontology grounding attempt."""

    text: str = Field(..., description="Original surface form from the extraction phase")
    concept_id: Optional[str] = Field(
        None, description="Ontology identifier (e.g. RXNORM:12345). None when unmatched."
    )
    label: Optional[str] = Field(None, description="Preferred label of the matched concept")
    provider: Optional[str] = Field(
        None, description="Ontology provider key (e.g. rxnorm, snomed)"
    )
    match_type: Literal["exact", "synonym", "fuzzy", "unmatched"] = Field(
        "unmatched", description="How the surface form was grounded"
    )
    score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Similarity score for the match. Exact/synonym matches use 1.0",
    )

    def is_matched(self) -> bool:
        return self.match_type != "unmatched" and self.concept_id is not None


class NormalizedTriple(BaseModel):
    """Normalized representation of a clinical fact."""

    raw_fact: Dict[str, Any] = Field(
        ..., description="Original fact dictionary before normalization"
    )
    drug: NormalizationMatch
    condition: NormalizationMatch
    relation: NormalizationMatch
    outcome: Optional[NormalizationMatch] = None
    side_effects: List[NormalizationMatch] = Field(default_factory=list)
    effect_size: Optional[str] = None
    confidence_interval: Optional[str] = None

    def matched_fields(self) -> Dict[str, bool]:
        """Convenience helper returning match flags for primary fields."""

        return {
            "drug": self.drug.is_matched(),
            "condition": self.condition.is_matched(),
            "relation": self.relation.is_matched(),
            "outcome": self.outcome.is_matched() if self.outcome else True,
            "side_effects": all(se.is_matched() for se in self.side_effects),
        }