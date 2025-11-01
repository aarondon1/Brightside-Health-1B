from __future__ import annotations
import json
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pathlib import Path
import openai
from pydantic import BaseModel, Field, ValidationError

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # if dotenv not installed, that's fine - will use environment variables
    pass

# Set up OpenAI client (reads OPENAI_API_KEY from environment)
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please set it with: export OPENAI_API_KEY=your_key_here")

client = openai.OpenAI(api_key=api_key)

# ----------------------------- 
# Normalization & Validation Helpers
# -----------------------------
def normalize_condition(condition: str) -> str:
    """Normalize condition names to canonical forms."""
    if not condition:
        return condition
    
    condition_lower = condition.lower().strip()
    
    normalization_map = {
        "anxious depression": "depression",
        "major depression": "major depressive disorder",
        "treatment resistant depression": "treatment-resistant depression",
        "treatment-resistant depression": "treatment-resistant depression",
        "trd": "treatment-resistant depression",
        "mdd": "major depressive disorder",
        "gad": "generalized anxiety disorder",
        "social anxiety disorder": "social anxiety",
        "ptsd": "post-traumatic stress disorder",
        "ocd": "obsessive compulsive disorder",
        "bipolar i disorder": "bipolar disorder",
        "bipolar ii disorder": "bipolar disorder",
    }
    
    normalized = normalization_map.get(condition_lower, condition)
    return normalized

INVALID_SIDE_EFFECTS = {
    "side effect frequency", "adverse event", "adverse events",
    "side effects", "adverse effect", "adverse effects",
    "effect", "outcome", "symptom", "symptoms",
    "placebo", "response", "remission", "improvement"
}

def is_valid_side_effect(side_effect: str) -> bool:
    """Check if a side effect is actually a specific medical side effect."""
    if not side_effect:
        return False
    
    se_lower = side_effect.lower().strip()
    
    # Reject generic/metadata terms
    if se_lower in INVALID_SIDE_EFFECTS:
        return False
    
    # Reject if too long (likely extraction error)
    if len(se_lower) > 100:
        return False
    
    return True

def clean_side_effects(side_effects: List[str]) -> List[str]:
    """Filter out invalid side effects."""
    if not side_effects:
        return []
    
    return [se for se in side_effects if is_valid_side_effect(se)]

def span_contains_value(span: str, value: str, strict: bool = True) -> bool:
    """Check if a value appears in the span text."""
    if not span or not value:
        return False
    
    span_lower = span.lower()
    value_lower = value.lower()
    
    if strict:
        # Exact substring match
        return value_lower in span_lower
    else:
        # Allow for slight variations (word boundaries)
        import re
        pattern = r'\b' + re.escape(value_lower) + r'\b'
        return bool(re.search(pattern, span_lower))


# -----------------------------
# Pydantic models for validation
# -----------------------------
class Triple(BaseModel):
    """A single extracted fact from the literature."""
    drug_name: str = Field(..., description="Name of the drug/medication")
    condition_name: str = Field(..., description="Medical condition being treated")
    relation: str = Field(..., description="Type of relationship (TREATS, IMPROVES, ASSOCIATED_WITH_SE, etc.)")
    outcome: Optional[str] = Field(None, description="Specific outcome measure if mentioned")
    side_effects: Optional[List[str]] = Field(default_factory=list, description="List of side effects mentioned")
    effect_size: Optional[str] = Field(None, description="Effect size, percentage, or numeric result if mentioned")
    confidence_interval: Optional[str] = Field(None, description="Confidence interval if provided")
    source_id: str = Field(..., description="Document source identifier")
    section: str = Field(..., description="Section where this fact was found")
    span: str = Field(..., description="Exact text span that supports this fact")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    
    @property
    def side_effects_list(self) -> List[str]:
        """Ensure side_effects is always a list, never None."""
        return self.side_effects if self.side_effects is not None else []

class ExtractionResult(BaseModel):
    """Collection of extracted triples from a document section."""
    triples: List[Triple] = Field(default_factory=list)
    section_name: str = Field(..., description="Name of the section processed")
    total_sentences: int = Field(..., description="Total sentences in this section")

# -----------------------------
# Extraction prompts
# -----------------------------
EXTRACTION_SYSTEM_PROMPT = """You are an expert clinical research extraction AI. Extract structured facts from medical literature.

ENTITIES TO EXTRACT:
- Drug: medications, treatments, interventions (e.g., "sertraline", "cognitive behavioral therapy", "escitalopram")
- Condition: diseases, disorders, symptoms (e.g., "major depressive disorder", "anxiety", "PTSD")
- Outcome: measures, scales, endpoints (e.g., "HAM-D score", "remission rate", "response rate")
- SideEffect: adverse events, side effects (e.g., "nausea", "headache", "sexual dysfunction")

RELATIONS TO EXTRACT:
- TREATS: drug/intervention treats condition
- IMPROVES: drug/intervention improves outcome/symptom  
- ASSOCIATED_WITH_SE: drug associated with side effect
- AUGMENTS: drug enhances effect of another treatment
- CONTRAINDICATED_FOR: drug should not be used for condition
- SUPERIOR_TO: one treatment is better than another
- EQUIVALENT_TO: treatments have similar efficacy

CRITICAL EXTRACTION RULES:
1. **Extract facts that are clearly supported by the text** - Don't infer beyond what the text suggests
2. **Drug name SHOULD appear in span** - The drug/treatment should be mentioned in the supporting text
3. **Condition can be explicit or contextually clear** - From context, it should be clear what condition is being discussed
4. **Span should include key supporting evidence** - Don't use fragments with dangling pronouns (e.g., "It showed...")
5. **Use appropriate condition names** - Use the condition name as written or a clear synonym
6. **For side effects**: Extract specific medical side effects, NOT generic terms like "adverse events" or "side effect frequency"
7. **Confidence scores should reflect certainty**:
   - 1.0: Explicit statement with quantitative results
   - 0.9: Clear direct statement of relationship
   - 0.8: Strong evidence from context
   - 0.7: Reasonable inference from text
   - <0.7: Avoid - only if extremely clear
8. **Extract numeric outcomes when available** (effect sizes, percentages, p-values)
9. **List side effects separately** for each drug
10. **Focus on Results and Discussion sections** - These have strongest evidence
11. **Include study context when relevant** (RCT, meta-analysis, observational)

Return valid JSON only. Do not include any text outside the JSON structure."""

EXTRACTION_USER_PROMPT = """Extract clinical facts from this section of a medical research paper:

DOCUMENT: {source_id}
SECTION: {section_name}
TEXT: {section_text}

Return a JSON object with this exact structure:
{{
  "triples": [
    {{
      "drug_name": "sertraline",
      "condition_name": "major depressive disorder", 
      "relation": "TREATS",
      "outcome": "HAM-D score reduction",
      "side_effects": ["nausea", "headache"],
      "effect_size": "50% improvement vs placebo",
      "confidence_interval": "95% CI: 1.2-2.8",
      "source_id": "{source_id}",
      "section": "{section_name}",
      "span": "Sertraline showed significant improvement in HAM-D scores with 50% of patients achieving remission",
      "confidence": 0.9
    }}
  ],
  "section_name": "{section_name}",
  "total_sentences": {total_sentences}
}}

Extract ALL relevant clinical facts from this section. Focus on:
- Treatment efficacy claims
- Side effect associations  
- Outcome measurements
- Comparative effectiveness
- Contraindications or warnings

Return valid JSON only."""

# -----------------------------
# Core extraction functions
# -----------------------------
def extract_from_section(
    section: Dict[str, Any], 
    source_id: str,
    model: str = "gpt-4o",  
    max_retries: int = 2
) -> ExtractionResult:
    """Extract facts from a single document section using LLM."""
    
    section_name = section["name"]
    section_text = section["text"]
    total_sentences = len(section.get("sentences", []))
    
    # Skip sections unlikely to have clinical facts
    skip_sections = {"references", "funding", "author information", "conflict", "acknowledgment"}
    if section_name.lower() in skip_sections or len(section_text.strip()) < 50:
        print(f"⏭ Skipping {section_name} (no clinical content expected)")
        return ExtractionResult(
            triples=[],
            section_name=section_name,
            total_sentences=total_sentences
        )
    
    # Truncate very long sections to stay within token limits
    max_chars = 4000
    truncated_text = section_text[:max_chars]
    if len(section_text) > max_chars:
        print(f"✂️ Truncated {section_name} from {len(section_text)} to {max_chars} chars")
    
    user_prompt = EXTRACTION_USER_PROMPT.format(
        source_id=source_id,
        section_name=section_name,
        section_text=truncated_text,
        total_sentences=total_sentences
    )
    
    for attempt in range(max_retries + 1):
        try:
            print(f"🤖 Processing {section_name} (attempt {attempt + 1})...")
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_completion_tokens=2000,  # Fixed: use max_completion_tokens instead of max_tokens
                response_format={"type": "json_object"}  # Ensures JSON response
            )
            
            content = response.choices[0].message.content
            raw_data = json.loads(content)
            
            # Clean up and filter triples before validation
            if "triples" in raw_data:
                cleaned_triples = []
                for triple in raw_data["triples"]:
                    # ===== POST-EXTRACTION VALIDATION & CLEANING =====
                    
                    # Fix None values
                    if triple.get("side_effects") is None:
                        triple["side_effects"] = []
                    
                    # Extract fields
                    drug_name = str(triple.get("drug_name", "")).strip()
                    condition_name = str(triple.get("condition_name", "")).strip()
                    span = str(triple.get("span", "")).strip()
                    
                    # Validate required fields
                    if not drug_name or not condition_name or not span:
                        print(f"   ⚠️  Skipping incomplete fact: drug='{drug_name}', condition='{condition_name}'")
                        continue
                    
                    # NEW: Verify drug appears in span (STRICT - drugs should always be mentioned)
                    if not span_contains_value(span, drug_name, strict=True):
                        print(f"   ⚠️  Drug '{drug_name}' not found in span, skipping")
                        continue
                    
                    # NEW: Check condition appears in span OR reasonable clinical context exists
                    # (More lenient than drug - conditions are often discussed contextually)
                    condition_in_span = span_contains_value(span, condition_name, strict=True)
                    
                    if not condition_in_span:
                        span_lower = span.lower()
                        # Look for clinical relationship indicators that suggest condition is implied
                        clinical_context_keywords = [
                            "treat", "therapy", "improvement", "remission", "response",
                            "efficacy", "symptom", "disorder", "disease", "syndrome",
                            "adverse", "side effect", "tolerated", "managed", "controlled"
                        ]
                        has_clinical_context = any(keyword in span_lower for keyword in clinical_context_keywords)
                        
                        # Also check if this is a side effect extraction (relation is ASSOCIATED_WITH_SE)
                        relation = str(triple.get("relation", "")).upper()
                        is_side_effect_fact = relation == "ASSOCIATED_WITH_SE"
                        
                        if not has_clinical_context and not is_side_effect_fact:
                            print(f"   ⚠️  Condition '{condition_name}' not in span and weak clinical context, skipping")
                            continue
                    
                    # NEW: Normalize condition name
                    triple["condition_name"] = normalize_condition(condition_name)
                    
                    # NEW: Clean side effects (remove metadata and invalid entries)
                    if triple.get("side_effects"):
                        old_count = len(triple.get("side_effects", []))
                        valid_ses = clean_side_effects(triple["side_effects"])
                        triple["side_effects"] = valid_ses
                        
                        if len(valid_ses) < old_count:
                            removed_count = old_count - len(valid_ses)
                            print(f"   ℹ️  Removed {removed_count} invalid side effects from fact")
                    
                    # NEW: Check for span completeness (no dangling pronouns)
                    # But allow common medical phrases and be more lenient
                    import re
                    span_first_words = span[:50].lower()
                    
                    # Only skip if starts with bare pronouns (not part of common medical phrases)
                    bad_pronoun_pattern = r'^(it|this|that|these|they|those|which)\s+(showed|demonstrated|resulted|found)'
                    if re.match(bad_pronoun_pattern, span_first_words):
                        print(f"   ⚠️  Span starts with unclear pronoun reference, skipping: '{span[:50]}...'")
                        continue
                    
                    # All validations passed
                    cleaned_triples.append(triple)
                
                raw_data["triples"] = cleaned_triples
            
            # Validate with Pydantic
            result = ExtractionResult(**raw_data)
            
            print(f"✓ Extracted {len(result.triples)} valid facts from {section_name}")
            return result
            
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"⚠️  Validation error on attempt {attempt + 1} for {section_name}: {e}")
            if attempt == max_retries:
                print(f"✗ Failed to extract from {section_name} after {max_retries + 1} attempts")
        except Exception as e:
            print(f"⚠️  Unexpected error on attempt {attempt + 1} for {section_name}: {e}")
            if attempt == max_retries:
                print(f"✗ Failed to extract from {section_name} after {max_retries + 1} attempts")
    
    # Return empty result if all attempts failed
    return ExtractionResult(triples=[], section_name=section_name, total_sentences=total_sentences)

def extract_from_document(parsed_doc: Dict[str, Any]) -> List[Triple]:
    """Extract facts from all sections of a parsed document."""
    
    source_id = parsed_doc["metadata"]["source_id"]
    sections = parsed_doc["sections"]
    
    print(f"🔍 Starting extraction from {source_id} ({len(sections)} sections)")
    
    all_triples = []
    for i, section in enumerate(sections, 1):
        print(f"\n📄 Section {i}/{len(sections)}: {section['name']}")
        result = extract_from_section(section, source_id)
        all_triples.extend(result.triples)
    
    print(f"\n✅ Extraction complete: {len(all_triples)} total facts from {source_id}")
    return all_triples

# -----------------------------
# Utility functions
# -----------------------------
def save_extraction_results(
    triples: List[Triple], 
    output_path: str | Path,
    include_metadata: bool = True
) -> None:
    """Save extraction results to JSON file."""
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if include_metadata:
        output = {
            "extracted_facts": [t.model_dump() for t in triples],
            "total_facts": len(triples),
            "extraction_timestamp": datetime.now().isoformat(),
            "extraction_model": "gpt-4o",
        }
    else:
        output = [t.model_dump() for t in triples]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Saved {len(triples)} extracted facts to {output_path}")

def load_parsed_document(json_path: str | Path) -> Dict[str, Any]:
    """Load a document parsed by Docling."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# -----------------------------
# Main extraction pipeline  
# -----------------------------
def extract_pipeline(parsed_json_path: str | Path, output_path: str | Path) -> List[Triple]:
    """Complete extraction pipeline: load parsed doc -> extract -> save -> return."""
    
    print(f"📂 Loading parsed document: {parsed_json_path}")
    parsed_doc = load_parsed_document(parsed_json_path)
    
    print(f"🔬 Extracting clinical facts...")
    triples = extract_from_document(parsed_doc)
    
    print(f"💾 Saving extraction results...")
    save_extraction_results(triples, output_path)
    
    return triples

if __name__ == "__main__":
    # Example usage for testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract clinical facts from parsed documents")
    parser.add_argument("--input", required=True, help="Path to parsed JSON file")
    parser.add_argument("--output", required=True, help="Path for extracted facts JSON")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    
    args = parser.parse_args()
    
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Please set OPENAI_API_KEY environment variable")
        exit(1)
    
    extract_pipeline(args.input, args.output)