from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from pydantic import BaseModel, Field, ValidationError

# Load environment variables if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# -----------------------------
# Validation Models
# -----------------------------
class ValidationIssue(BaseModel):
    """Represents a validation problem with an extracted fact."""
    fact_index: int
    issue_type: str
    severity: str  # "error", "warning", "info"
    field: str
    message: str
    suggestion: Optional[str] = None

class ValidationReport(BaseModel):
    """Summary of validation results."""
    total_facts: int
    valid_facts: int
    invalid_facts: int
    warnings: int
    issues: List[ValidationIssue]
    
    def print_summary(self):
        """Print a human-readable validation summary."""
        print(f"\n📊 Validation Report:")
        print(f"   Total facts: {self.total_facts}")
        print(f"   ✅ Valid: {self.valid_facts}")
        print(f"   ❌ Invalid: {self.invalid_facts}")
        print(f"   ⚠️  Warnings: {self.warnings}")
        
        if self.issues:
            print(f"\n🔍 Issues found:")
            for issue in self.issues[:10]:  # Show first 10 issues
                icon = "❌" if issue.severity == "error" else "⚠️"
                print(f"   {icon} Fact #{issue.fact_index}: {issue.message}")
                if issue.suggestion:
                    print(f"      💡 Suggestion: {issue.suggestion}")

# -----------------------------
# Validation Rules & Lists
# -----------------------------

# Medical conditions (partial list - would be expanded with ontologies)
VALID_CONDITIONS = {
    "depression", "major depressive disorder", "treatment-resistant depression",
    "anxiety", "generalized anxiety disorder", "panic disorder", "social anxiety",
    "bipolar disorder", "schizophrenia", "ptsd", "post-traumatic stress disorder",
    "adhd", "attention deficit hyperactivity disorder", "autism spectrum disorder",
    "obsessive compulsive disorder", "ocd", "eating disorders", "anorexia", "bulimia"
}

# Words that indicate this is NOT a medical condition
CONDITION_EXCLUSION_WORDS = {
    "treatment", "therapy", "medication", "drug", "intervention", "approach",
    "method", "technique", "procedure", "protocol", "regimen", "strategy",
    "care", "management", "typical medical treatment", "standard care",
    "placebo", "control", "baseline", "comparison", "comparator"
}

# Valid drug/treatment patterns
DRUG_NAME_PATTERNS = {
    # SSRIs
    "sertraline", "fluoxetine", "paroxetine", "escitalopram", "citalopram", "fluvoxamine",
    # SNRIs  
    "venlafaxine", "duloxetine", "desvenlafaxine", "levomilnacipran",
    # Atypicals
    "bupropion", "mirtazapine", "trazodone", "nefazodone",
    # MAOIs
    "phenelzine", "tranylcypromine", "isocarboxazid", "selegiline",
    # Tricyclics
    "amitriptyline", "imipramine", "nortriptyline", "desipramine",
    # Drug classes
    "ssri", "ssris", "selective serotonin reuptake inhibitor", "snri", "snris",
    "tricyclic", "tricyclics", "maoi", "maois", "antidepressant", "antidepressants",
    # Non-drug treatments
    "cbt", "cognitive behavioral therapy", "psychotherapy", "ect", "tms", "vns",
    "mindfulness", "meditation", "exercise"
}

# Valid relations
VALID_RELATIONS = {
    "TREATS", "IMPROVES", "ASSOCIATED_WITH_SE", "AUGMENTS", 
    "CONTRAINDICATED_FOR", "SUPERIOR_TO", "EQUIVALENT_TO", "INFERIOR_TO"
}

# Side effects vocabulary
COMMON_SIDE_EFFECTS = {
    "nausea", "headache", "dizziness", "fatigue", "insomnia", "somnolence",
    "dry mouth", "constipation", "diarrhea", "sexual dysfunction", "weight gain",
    "weight loss", "tremor", "sweating", "blurred vision", "anxiety", "agitation"
}

# -----------------------------
# Validation Functions
# -----------------------------
class FactValidator:
    """Validates extracted clinical facts using rules and heuristics."""
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
    
    def validate_fact(self, fact: Dict[str, Any], index: int) -> bool:
        """Validate a single fact. Returns True if valid, False if invalid."""
        is_valid = True
        
        # Required field validation
        if not self._validate_required_fields(fact, index):
            is_valid = False
            
        # Content validation
        if not self._validate_drug_name(fact, index):
            is_valid = False
            
        if not self._validate_condition_name(fact, index):
            is_valid = False
            
        if not self._validate_relation(fact, index):
            is_valid = False
            
        if not self._validate_confidence(fact, index):
            is_valid = False
            
        # Consistency validation
        self._validate_span_consistency(fact, index)
        self._validate_side_effects(fact, index)
        self._validate_effect_size_format(fact, index)
        
        return is_valid
    
    def _validate_required_fields(self, fact: Dict[str, Any], index: int) -> bool:
        """Check that all required fields are present and non-empty."""
        required_fields = ["drug_name", "condition_name", "relation", "span", "confidence"]
        is_valid = True
        
        for field in required_fields:
            if field not in fact or not fact[field] or str(fact[field]).strip() == "":
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="missing_required_field",
                    severity="error",
                    field=field,
                    message=f"Required field '{field}' is missing or empty",
                    suggestion=f"Ensure {field} has a valid value"
                ))
                is_valid = False
        
        return is_valid
    
    def _validate_drug_name(self, fact: Dict[str, Any], index: int) -> bool:
        """Validate drug name field."""
        drug_name = str(fact.get("drug_name", "")).lower().strip()
        
        if not drug_name:
            return False  # Already caught by required fields
            
        # Check for overly long drug names (likely extraction errors)
        if len(drug_name) > 100:
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="drug_name_too_long",
                severity="warning",
                field="drug_name",
                message=f"Drug name unusually long ({len(drug_name)} chars): {drug_name[:50]}...",
                suggestion="Check if this extracted the full sentence instead of just the drug name"
            ))
        
        # Check if it's a known drug/treatment
        if not any(pattern in drug_name for pattern in DRUG_NAME_PATTERNS):
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="unknown_drug",
                severity="info",
                field="drug_name",
                message=f"Drug name not in known list: {drug_name}",
                suggestion="Verify this is a valid medication or treatment"
            ))
        
        return True
    
    def _validate_condition_name(self, fact: Dict[str, Any], index: int) -> bool:
        """Validate condition name - this catches the main error from your example."""
        condition_name = str(fact.get("condition_name", "")).lower().strip()
        
        if not condition_name:
            return False  # Already caught by required fields
        
        # Check for treatment words in condition name (major error pattern)
        for exclusion_word in CONDITION_EXCLUSION_WORDS:
            if exclusion_word in condition_name:
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="invalid_condition_name",
                    severity="error",
                    field="condition_name",
                    message=f"Condition name contains treatment word '{exclusion_word}': {condition_name}",
                    suggestion="This should be a medical condition, not a treatment. Check the extraction logic."
                ))
                return False
        
        # Check if it's a known condition
        if condition_name not in VALID_CONDITIONS:
            # Check for partial matches
            partial_matches = [cond for cond in VALID_CONDITIONS if cond in condition_name or condition_name in cond]
            if partial_matches:
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="condition_name_variant",
                    severity="info",
                    field="condition_name",
                    message=f"Condition name variant: {condition_name}",
                    suggestion=f"Consider normalizing to: {partial_matches[0]}"
                ))
            else:
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="unknown_condition",
                    severity="info",
                    field="condition_name",
                    message=f"Condition not in known list: {condition_name}",
                    suggestion="Verify this is a valid medical condition"
                ))
        
        return True
    
    def _validate_relation(self, fact: Dict[str, Any], index: int) -> bool:
        """Validate relation type."""
        relation = str(fact.get("relation", "")).upper().strip()
        
        if relation not in VALID_RELATIONS:
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="invalid_relation",
                severity="error",
                field="relation",
                message=f"Invalid relation type: {relation}",
                suggestion=f"Use one of: {', '.join(VALID_RELATIONS)}"
            ))
            return False
        
        return True
    
    def _validate_confidence(self, fact: Dict[str, Any], index: int) -> bool:
        """Validate confidence score."""
        confidence = fact.get("confidence")
        
        if confidence is None:
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="missing_confidence",
                severity="error",
                field="confidence",
                message="Confidence score is missing",
                suggestion="Confidence must be a number between 0.0 and 1.0"
            ))
            return False
        
        try:
            conf_float = float(confidence)
            if not (0.0 <= conf_float <= 1.0):
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="invalid_confidence_range",
                    severity="error",
                    field="confidence",
                    message=f"Confidence {conf_float} outside valid range [0.0, 1.0]",
                    suggestion="Confidence must be between 0.0 and 1.0"
                ))
                return False
        except (ValueError, TypeError):
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="invalid_confidence_type",
                severity="error",
                field="confidence",
                message=f"Confidence must be numeric, got: {type(confidence).__name__}",
                suggestion="Confidence must be a number between 0.0 and 1.0"
            ))
            return False
        
        return True
    
    def _validate_span_consistency(self, fact: Dict[str, Any], index: int):
        """Check if the span actually supports the extracted fact."""
        span = str(fact.get("span", "")).lower()
        drug_name = str(fact.get("drug_name", "")).lower()
        condition_name = str(fact.get("condition_name", "")).lower()
        
        # Check if drug name appears in span
        if drug_name and drug_name not in span:
            # Check for partial matches or abbreviations
            drug_words = drug_name.split()
            if not any(word in span for word in drug_words if len(word) > 2):
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="drug_not_in_span",
                    severity="warning",
                    field="span",
                    message=f"Drug name '{drug_name}' not found in supporting text",
                    suggestion="Check if extraction correctly identified the drug mentioned in the span"
                ))
        
        # Check if condition appears in span (more lenient for conditions)
        if condition_name and len(condition_name) > 3:
            condition_words = condition_name.split()
            if not any(word in span for word in condition_words if len(word) > 3):
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="condition_not_in_span",
                    severity="info",
                    field="span",
                    message=f"Condition '{condition_name}' not clearly mentioned in span",
                    suggestion="Verify the span supports the extracted condition"
                ))
    
    def _validate_side_effects(self, fact: Dict[str, Any], index: int):
        """Validate side effects list."""
        side_effects = fact.get("side_effects", [])
        
        if not isinstance(side_effects, list):
            self.issues.append(ValidationIssue(
                fact_index=index,
                issue_type="invalid_side_effects_type",
                severity="warning",
                field="side_effects",
                message="Side effects should be a list",
                suggestion="Convert to list format: ['nausea', 'headache']"
            ))
            return
        
        for se in side_effects:
            se_lower = str(se).lower().strip()
            if se_lower not in COMMON_SIDE_EFFECTS:
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="unknown_side_effect",
                    severity="info",
                    field="side_effects",
                    message=f"Unknown side effect: {se}",
                    suggestion="Verify this is a valid medical side effect"
                ))
    
    def _validate_effect_size_format(self, fact: Dict[str, Any], index: int):
        """Check effect size format."""
        effect_size = fact.get("effect_size")
        
        if effect_size and str(effect_size).strip():
            effect_str = str(effect_size).lower()
            
            # Look for common patterns
            has_number = bool(re.search(r'\d', effect_str))
            has_percent = '%' in effect_str
            has_stats = any(word in effect_str for word in ['cohen', 'nnt', 'odds ratio', 'hazard ratio'])
            
            if not (has_number or has_stats):
                self.issues.append(ValidationIssue(
                    fact_index=index,
                    issue_type="vague_effect_size",
                    severity="info",
                    field="effect_size",
                    message=f"Effect size lacks quantitative data: {effect_size}",
                    suggestion="Include specific numbers, percentages, or statistical measures when available"
                ))

# -----------------------------
# Main Validation Pipeline
# -----------------------------
def validate_extracted_facts(facts_data: Dict[str, Any]) -> Tuple[List[Dict], ValidationReport]:
    """
    Validate extracted facts and return clean facts + validation report.
    
    Args:
        facts_data: Dict containing extracted_facts list and metadata
        
    Returns:
        Tuple of (valid_facts_list, validation_report)
    """
    validator = FactValidator()
    
    # Extract facts list from the data structure
    if "extracted_facts" in facts_data:
        facts = facts_data["extracted_facts"]
    elif isinstance(facts_data, list):
        facts = facts_data
    else:
        raise ValueError("Input must contain 'extracted_facts' key or be a list of facts")
    
    valid_facts = []
    invalid_count = 0
    warning_count = 0
    
    print(f"🔍 Validating {len(facts)} extracted facts...")
    
    for i, fact in enumerate(facts):
        is_valid = validator.validate_fact(fact, i)
        
        if is_valid:
            valid_facts.append(fact)
        else:
            invalid_count += 1
    
    # Count warnings
    warning_count = sum(1 for issue in validator.issues if issue.severity == "warning")
    
    report = ValidationReport(
        total_facts=len(facts),
        valid_facts=len(valid_facts),
        invalid_facts=invalid_count,
        warnings=warning_count,
        issues=validator.issues
    )
    
    return valid_facts, report

def save_validation_results(
    valid_facts: List[Dict],
    report: ValidationReport,
    output_path: str | Path,
    issues_path: Optional[str | Path] = None
):
    """Save validation results to files."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save clean facts
    clean_data = {
        "validated_facts": valid_facts,
        "total_facts": len(valid_facts),
        "validation_summary": {
            "original_count": report.total_facts,
            "valid_count": report.valid_facts,
            "invalid_count": report.invalid_facts,
            "warning_count": report.warnings
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Saved {len(valid_facts)} validated facts to {output_path}")
    
    # Save issues report if requested
    if issues_path:
        issues_path = Path(issues_path)
        issues_data = {
            "validation_report": report.model_dump(),
            "issues_by_type": {}
        }
        
        # Group issues by type for analysis
        for issue in report.issues:
            issue_type = issue.issue_type
            if issue_type not in issues_data["issues_by_type"]:
                issues_data["issues_by_type"][issue_type] = []
            issues_data["issues_by_type"][issue_type].append(issue.model_dump())
        
        with open(issues_path, 'w', encoding='utf-8') as f:
            json.dump(issues_data, f, ensure_ascii=False, indent=2)
        
        print(f"📋 Saved validation issues to {issues_path}")

# -----------------------------
# CLI Interface
# -----------------------------
def main():
    """Command-line interface for validation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate extracted clinical facts")
    parser.add_argument("--input", required=True, help="Path to extracted facts JSON file")
    parser.add_argument("--output", required=True, help="Path for validated facts output")
    parser.add_argument("--issues", help="Path to save validation issues report")
    
    args = parser.parse_args()
    
    # Load extracted facts
    with open(args.input, 'r', encoding='utf-8') as f:
        facts_data = json.load(f)
    
    # Validate
    valid_facts, report = validate_extracted_facts(facts_data)
    
    # Print report
    report.print_summary()
    
    # Save results
    save_validation_results(valid_facts, report, args.output, args.issues)
    
    print(f"\n✅ Validation complete!")
    print(f"📊 Results: {report.valid_facts}/{report.total_facts} facts passed validation")

if __name__ == "__main__":
    main()