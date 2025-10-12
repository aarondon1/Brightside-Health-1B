#!/usr/bin/env python3
"""
Automated quality assessment for extracted facts using multiple methods.
Usage: python3 -m scripts.auto_validate_quality --input data/processed/validated/sample_validated.json

# Run this once to baseline quality
  python3 -m scripts.auto_validate_quality \
  --input data/processed/validated/sample_extracted_v2_validated.json \
  --methods heuristic \
  --sample-size 30
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Optional: Import OpenAI for LLM-based validation
try:
    import openai
    OPENAI_AVAILABLE = True
    client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY')) if os.getenv('OPENAI_API_KEY') else None
except ImportError:
    OPENAI_AVAILABLE = False
    client = None

# -----------------------------
# Method 1: Heuristic-Based Validation
# -----------------------------
def heuristic_quality_check(fact: Dict) -> Dict[str, any]:
    """
    Use heuristics to estimate if a fact is likely correct.
    Returns quality score and reasoning.
    """
    score = 100  # Start at perfect
    issues = []
    
    drug_name = str(fact.get('drug_name', '')).lower()
    condition_name = str(fact.get('condition_name', '')).lower()
    relation = fact.get('relation', '')
    span = str(fact.get('span', '')).lower()
    confidence = fact.get('confidence', 0)
    
    # Check 1: Does drug appear in span?
    drug_words = [w for w in drug_name.split() if len(w) > 2]
    if drug_words and not any(word in span for word in drug_words):
        score -= 30
        issues.append("Drug not found in supporting text")
    
    # Check 2: Does condition appear in span or nearby context?
    condition_words = [w for w in condition_name.split() if len(w) > 3]
    if condition_words and not any(word in span for word in condition_words):
        # More lenient - condition might be implied
        score -= 10
        issues.append("Condition not explicitly mentioned in span")
    
    # Check 3: Relation consistency
    relation_keywords = {
        'TREATS': ['treat', 'treatment', 'effective', 'efficacy', 'therapy'],
        'IMPROVES': ['improve', 'better', 'enhance', 'increase', 'reduce'],
        'ASSOCIATED_WITH_SE': ['side effect', 'adverse', 'tolera', 'experience'],
        'EQUIVALENT_TO': ['similar', 'equivalent', 'not better', 'no difference', 'comparable'],
        'SUPERIOR_TO': ['better than', 'superior', 'more effective', 'outperform'],
    }
    
    if relation in relation_keywords:
        keywords = relation_keywords[relation]
        if not any(kw in span for kw in keywords):
            score -= 20
            issues.append(f"Span doesn't contain typical {relation} language")
    
    # Check 4: Confidence alignment
    if confidence < 0.6:
        score -= 15
        issues.append("Low confidence score")
    
    # Check 5: Span length (too short = missing context)
    if len(span) < 20:
        score -= 10
        issues.append("Very short span, may lack context")
    
    # Check 6: Treatment words in condition name (major error)
    treatment_words = ['treatment', 'therapy', 'medication', 'drug', 'care']
    if any(word in condition_name for word in treatment_words):
        score -= 50
        issues.append("CRITICAL: Condition name contains treatment words")
    
    return {
        'quality_score': max(0, score),
        'likely_correct': score >= 70,
        'issues': issues
    }

# -----------------------------
# Method 2: NLI (Natural Language Inference)
# -----------------------------
def nli_quality_check(fact: Dict) -> Dict[str, any]:
    """
    Use textual entailment: Does the span support the claim?
    Requires sentence-transformers or similar library.
    """
    try:
        from sentence_transformers import SentenceTransformer, util
        
        # Load model (cache it globally in production)
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Construct claim from fact
        drug = fact.get('drug_name', '')
        condition = fact.get('condition_name', '')
        relation = fact.get('relation', '').replace('_', ' ').lower()
        claim = f"{drug} {relation} {condition}"
        
        # Get span
        span = fact.get('span', '')
        
        # Compute similarity
        embeddings = model.encode([claim, span])
        similarity = float(util.cos_sim(embeddings[0], embeddings[1])[0][0])
        
        # Threshold: >0.5 = likely supported
        return {
            'quality_score': int(similarity * 100),
            'likely_correct': similarity > 0.5,
            'similarity': similarity,
            'method': 'sentence_similarity'
        }
        
    except ImportError:
        return {
            'quality_score': None,
            'likely_correct': None,
            'error': 'sentence-transformers not installed'
        }

# -----------------------------
# Method 3: LLM-as-Judge
# -----------------------------
def llm_judge_quality_check(fact: Dict, model: str = "gpt-4o-mini") -> Dict[str, any]:
    """
    Use another LLM call to verify the extraction.
    Most accurate but costs API calls.
    """
    if not OPENAI_AVAILABLE or not client:
        return {
            'quality_score': None,
            'likely_correct': None,
            'error': 'OpenAI not available or API key not set'
        }
    
    drug = fact.get('drug_name', '')
    condition = fact.get('condition_name', '')
    relation = fact.get('relation', '')
    span = fact.get('span', '')
    
    prompt = f"""You are a fact-checker for medical literature extraction.

EXTRACTED FACT:
- Drug/Treatment: {drug}
- Relation: {relation}
- Condition: {condition}

SUPPORTING TEXT:
"{span}"

TASK: Does the supporting text accurately support this extracted fact?

Respond in JSON format:
{{
  "is_correct": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation",
  "issues": ["list", "of", "problems"] or []
}}

Be strict: The fact must be directly supported by the text."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        return {
            'quality_score': int(result.get('confidence', 0) * 100),
            'likely_correct': result.get('is_correct', False),
            'reasoning': result.get('reasoning', ''),
            'issues': result.get('issues', []),
            'method': 'llm_judge'
        }
        
    except Exception as e:
        return {
            'quality_score': None,
            'likely_correct': None,
            'error': str(e)
        }

# -----------------------------
# Method 4: Cross-Reference with Knowledge Base
# -----------------------------
def knowledge_base_check(fact: Dict) -> Dict[str, any]:
    """
    Check if the fact is consistent with known medical knowledge.
    Requires medical knowledge base or API (e.g., UMLS, DrugBank).
    """
    # Placeholder - would integrate with medical knowledge bases
    drug = fact.get('drug_name', '').lower()
    condition = fact.get('condition_name', '').lower()
    relation = fact.get('relation', '')
    
    # Simple example: known drug-condition pairs
    known_pairs = {
        ('sertraline', 'depression'): 'TREATS',
        ('fluoxetine', 'depression'): 'TREATS',
        ('escitalopram', 'anxiety'): 'TREATS',
        ('ssri', 'depression'): 'TREATS',
        ('ssris', 'depression'): 'TREATS',
    }
    
    # Check if this is a known valid combination
    is_known = False
    for (known_drug, known_cond), known_rel in known_pairs.items():
        if known_drug in drug and known_cond in condition:
            if relation == known_rel:
                is_known = True
                break
    
    return {
        'quality_score': 90 if is_known else None,
        'likely_correct': is_known if is_known else None,
        'is_known_combination': is_known,
        'method': 'knowledge_base'
    }

# -----------------------------
# Combined Quality Assessment
# -----------------------------
def assess_fact_quality(fact: Dict, methods: List[str] = None) -> Dict:
    """
    Run multiple quality checks and combine results.
    """
    if methods is None:
        methods = ['heuristic', 'nli', 'knowledge_base']  # Default: fast methods
    
    results = {}
    
    if 'heuristic' in methods:
        results['heuristic'] = heuristic_quality_check(fact)
    
    if 'nli' in methods:
        results['nli'] = nli_quality_check(fact)
    
    if 'llm_judge' in methods:
        results['llm_judge'] = llm_judge_quality_check(fact)
    
    if 'knowledge_base' in methods:
        results['knowledge_base'] = knowledge_base_check(fact)
    
    # Combine scores (weighted average of available methods)
    scores = [r['quality_score'] for r in results.values() if r.get('quality_score') is not None]
    avg_score = sum(scores) / len(scores) if scores else None
    
    # Majority vote on likely_correct
    votes = [r['likely_correct'] for r in results.values() if r.get('likely_correct') is not None]
    likely_correct = sum(votes) / len(votes) > 0.5 if votes else None
    
    return {
        'fact': fact,
        'quality_score': avg_score,
        'likely_correct': likely_correct,
        'method_results': results
    }

# -----------------------------
# Batch Assessment
# -----------------------------
def assess_dataset_quality(
    facts: List[Dict],
    methods: List[str] = None,
    sample_size: int = None
) -> Dict:
    """
    Assess quality of entire dataset.
    """
    import random
    
    if sample_size and sample_size < len(facts):
        print(f"📊 Sampling {sample_size} facts for quality assessment...")
        facts = random.sample(facts, sample_size)
    
    print(f"🔍 Assessing quality of {len(facts)} facts...")
    print(f"   Methods: {', '.join(methods or ['heuristic', 'nli', 'knowledge_base'])}")
    
    results = []
    for i, fact in enumerate(facts):
        if (i + 1) % 10 == 0:
            print(f"   Progress: {i+1}/{len(facts)}")
        
        result = assess_fact_quality(fact, methods)
        results.append(result)
    
    # Calculate statistics
    valid_scores = [r['quality_score'] for r in results if r['quality_score'] is not None]
    avg_quality = sum(valid_scores) / len(valid_scores) if valid_scores else 0
    
    likely_correct = [r for r in results if r['likely_correct'] is True]
    estimated_precision = len(likely_correct) / len(results) if results else 0
    
    return {
        'total_facts': len(facts),
        'average_quality_score': avg_quality,
        'estimated_precision': estimated_precision,
        'results': results
    }

# -----------------------------
# CLI
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Automated quality assessment for extracted facts"
    )
    parser.add_argument("--input", required=True, help="Path to validated facts JSON")
    parser.add_argument("--output", help="Path for quality report output")
    parser.add_argument("--methods", nargs="+", 
                       choices=['heuristic', 'nli', 'llm_judge', 'knowledge_base'],
                       default=['heuristic'],
                       help="Quality assessment methods to use")
    parser.add_argument("--sample-size", type=int, help="Only assess a random sample (faster)")
    parser.add_argument("--use-llm", action="store_true", help="Include LLM-based validation (costs API calls)")
    
    args = parser.parse_args()
    
    # Add LLM method if requested
    if args.use_llm:
        if 'llm_judge' not in args.methods:
            args.methods.append('llm_judge')
    
    # Auto-generate output path
    if not args.output:
        input_path = Path(args.input)
        output_dir = Path("eval")
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = output_dir / f"{input_path.stem}_quality_report.json"
    
    print(f"📂 Loading facts from: {args.input}")
    
    # Load facts
    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if "validated_facts" in data:
        facts = data["validated_facts"]
    elif isinstance(data, list):
        facts = data
    else:
        print("❌ Invalid input format")
        return
    
    print(f"📊 Total facts: {len(facts)}")
    
    # Run assessment
    report = assess_dataset_quality(facts, args.methods, args.sample_size)
    
    # Save report
    output_path = Path(args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("📊 AUTOMATED QUALITY ASSESSMENT REPORT")
    print("="*60)
    print(f"Total facts assessed: {report['total_facts']}")
    print(f"Average quality score: {report['average_quality_score']:.1f}/100")
    print(f"Estimated precision: {report['estimated_precision']:.1%}")
    print("="*60)
    
    if report['estimated_precision'] >= 0.85:
        print("✅ QUALITY CHECK PASSED (≥85% precision)")
        print("🎯 Safe to proceed to normalization step")
    elif report['estimated_precision'] >= 0.70:
        print("⚠️  QUALITY CHECK WARNING (70-85% precision)")
        print("🔍 Review common error patterns before proceeding")
    else:
        print("❌ QUALITY CHECK FAILED (<70% precision)")
        print("🛠️  Improve extraction prompts and re-run")
    
    print(f"\n💾 Full report saved to: {output_path}")
    
    # Show sample of low-quality facts
    low_quality = [r for r in report['results'] if r.get('quality_score', 100) < 70]
    if low_quality:
        print(f"\n⚠️  Found {len(low_quality)} low-quality facts. Examples:")
        for r in low_quality[:3]:
            fact = r['fact']
            print(f"\n   {fact.get('drug_name')} {fact.get('relation')} {fact.get('condition_name')}")
            print(f"   Quality: {r.get('quality_score', 'N/A')}/100")
            if 'heuristic' in r['method_results']:
                issues = r['method_results']['heuristic'].get('issues', [])
                if issues:
                    print(f"   Issues: {', '.join(issues[:2])}")

if __name__ == "__main__":
    main()