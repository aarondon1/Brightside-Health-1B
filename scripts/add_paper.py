import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.ingest_docling import parse_document
from src.core.extract_llm import extract_pipeline
from src.core.validate import validate_extracted_facts, save_validation_results
from src.core.normalize_ontology import OntologyNormalizer
# from src.core.graph_store import upsert_to_graph  # Implement when ready


def assess_quality(facts: List[Dict], methods: List[str] = ["heuristic"]) -> Dict:
    """Run quality assessment on validated facts."""
    from scripts.auto_validate_quality import assess_dataset_quality
    return assess_dataset_quality(facts, methods=methods)


def load_papers_from_file(file_path: Path) -> List[str]:
    """Load paper sources (URLs or local paths) from a text file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Paper list file not found: {file_path}")
    sources: List[str] = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                sources.append(line)
    return sources


def process_single_paper(
    source: str,
    output_base: Path,
    quality_threshold: float = 0.70,
    paper_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
    min_quality_score: Optional[int] = None # 0..100, filter facts by quality score before normalization
) -> dict:
    """Process one paper through the full pipeline with quality gates."""
    # Generate paper_id
    if paper_id is None:
        if source.startswith('http'):
            import hashlib
            paper_id = hashlib.md5(source.encode()).hexdigest()[:12]
        else:
            paper_id = Path(source).stem

    metadata = metadata or {}

    print(f"\n{'='*60}")
    print(f"📄 Processing: {paper_id}")
    if metadata.get('title'):
        print(f"📖 Title: {metadata['title']}")
    if metadata.get('year'):
        print(f"📅 Year: {metadata['year']}")
    print(f"🔗 Source: {source}")
    print(f"{'='*60}\n")

    # 1) Parse
    print("1️⃣ Parsing document...")
    parsed_path = output_base / "interim" / f"{paper_id}_parsed.json"
    parsed_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        parsed_doc = parse_document(source, source_id=paper_id)
        if metadata:
            parsed_doc["metadata"].update(metadata)
        parsed_path.write_text(json.dumps(parsed_doc, indent=2), encoding="utf-8")
        print(f"   ✅ Parsed → {parsed_path}")
    except Exception as e:
        print(f"   ❌ Parse failed: {e}")
        raise

    # 2) Extract
    print("\n2️⃣ Extracting facts...")
    extracted_path = output_base / "processed" / "extracted" / f"{paper_id}_extracted.json"
    extracted_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        triples = extract_pipeline(parsed_path, extracted_path)
        print(f"   ✅ Extracted {len(triples)} facts → {extracted_path}")
    except Exception as e:
        print(f"   ❌ Extraction failed: {e}")
        raise

    # 3) Validate
    print("\n3️⃣ Validating facts...")
    validated_path = output_base / "processed" / "validated" / f"{paper_id}_validated.json"
    issues_path = output_base / "processed" / "validated" / f"{paper_id}_issues.json"
    validated_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        facts_data = json.loads(extracted_path.read_text(encoding="utf-8"))
        valid_facts, report = validate_extracted_facts(facts_data)
        save_validation_results(valid_facts, report, validated_path, issues_path)
        print(f"   ✅ Validated {len(valid_facts)}/{report.total_facts} facts → {validated_path}")
    except Exception as e:
        print(f"   ❌ Validation failed: {e}")
        raise

        # 3.5) Quality assessment (gate)
    print("\n🔍 3.5 Quality Assessment...")
    quality_report_path = output_base / "eval" / f"{paper_id}_quality_report.json"
    quality_report_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        quality_report = assess_quality(valid_facts, methods=["heuristic"])
        quality_report_path.write_text(json.dumps(quality_report, indent=2), encoding="utf-8")
        
        precision = quality_report.get("estimated_precision", 0)  # 0..1
        avg_quality = quality_report.get("average_quality_score", 0)  # 0..100
        
        print(f"   📊 Quality Score: {avg_quality:.1f}/100")
        print(f"   📊 Estimated Precision: {precision:.1%}")

        # Optional: filter facts by min_quality_score and recompute precision
        validated_path_to_use = output_base / "processed" / "validated" / f"{paper_id}_validated.json"
        filtered_mode = False
        if min_quality_score is not None:
            print(f"   ⚙️  Applying min_quality_score={min_quality_score} filter...")
            results = quality_report.get("results", [])
            high_conf_results = [r for r in results if r.get("quality_score") is not None and r["quality_score"] >= min_quality_score]
            filtered_facts = [r["fact"] for r in high_conf_results]
            print(f"   📉 Filtered facts: kept {len(filtered_facts)}/{len(valid_facts)}")

            # Recompute quality on filtered set
            filtered_quality_report = assess_quality(filtered_facts, methods=["heuristic"])
            filtered_precision = filtered_quality_report.get("estimated_precision", 0)
            filtered_avg_quality = filtered_quality_report.get("average_quality_score", 0)

            # Save filtered validated facts and filtered report
            validated_path_hq = output_base / "processed" / "validated" / f"{paper_id}_validated_hq.json"
            issues_path_hq = output_base / "processed" / "validated" / f"{paper_id}_issues_hq.json"
            save_validation_results(filtered_facts, report, validated_path_hq, issues_path_hq)  # reuse same report metadata
            quality_report_hq_path = output_base / "eval" / f"{paper_id}_quality_report_hq.json"
            quality_report_hq_path.write_text(json.dumps(filtered_quality_report, indent=2), encoding="utf-8")
            validated_path_to_use = validated_path_hq
            filtered_mode = True

            print(f"   📊 Filtered Quality Score: {filtered_avg_quality:.1f}/100")
            print(f"   📊 Filtered Estimated Precision: {filtered_precision:.1%}")

            if filtered_precision < quality_threshold or len(filtered_facts) == 0:
                print(f"\n   ❌ QUALITY GATE FAILED (after filtering)")
                print(f"   📉 Precision {filtered_precision:.1%} < threshold {quality_threshold:.1%}")
                print(f"   💾 Reports: {quality_report_path} (full), {quality_report_hq_path} (filtered)")
                return {
                    "paper_id": paper_id,
                    "source": source,
                    "parsed": str(parsed_path),
                    "extracted": str(extracted_path),
                    "validated": str(validated_path if not filtered_mode else validated_path_hq),
                    "quality_report": str(quality_report_hq_path),
                    "facts_extracted": len(triples),
                    "facts_validated": len(filtered_facts),
                    "quality_score": filtered_avg_quality,
                    "estimated_precision": filtered_precision,
                    "status": "QUALITY_GATE_FAILED"
                }
            else:
                # Overwrite counters so downstream summary reflects filtered set
                avg_quality = filtered_avg_quality
                precision = filtered_precision
                valid_facts = filtered_facts  # downstream metrics
                print(f"   ✅ Quality gate passed after filtering ({precision:.1%} ≥ {quality_threshold:.1%})")

        # No filtering: enforce gate on full set
        if not filtered_mode and precision < quality_threshold:
            print(f"\n   ❌ QUALITY GATE FAILED")
            print(f"   📉 Precision {precision:.1%} < threshold {quality_threshold:.1%}")
            print(f"   💡 Review quality report: {quality_report_path}")
            return {
                "paper_id": paper_id,
                "source": source,
                "parsed": str(parsed_path),
                "extracted": str(extracted_path),
                "validated": str(validated_path),
                "quality_report": str(quality_report_path),
                "facts_extracted": len(triples),
                "facts_validated": len(valid_facts),
                "quality_score": avg_quality,
                "estimated_precision": precision,
                "status": "QUALITY_GATE_FAILED"
            }
        if not filtered_mode:
            print(f"   ✅ Quality gate passed ({precision:.1%} ≥ {quality_threshold:.1%})")
    except Exception as e:
        print(f"   ⚠️  Quality assessment failed: {e}")
        print(f"   ⏭  Proceeding to normalization anyway...")
        avg_quality = None
        precision = None
        validated_path_to_use = validated_path  # fallback

    # 4) Normalize (use filtered or full validated file)
    print("\n4️⃣ Normalizing to ontologies...")
    normalized_path = output_base / "processed" / "normalized" / f"{paper_id}_normalized.json"
    normalized_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        normalizer = OntologyNormalizer(
            config_path="configs/mappings.yaml",
            min_fuzzy_score=0.86,
        )
        normalized = normalizer.normalize_file(validated_path_to_use)
        payload = {"normalized_facts": [fact.model_dump() for fact in normalized]}
        normalized_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"   ✅ Normalized {len(normalized)} facts → {normalized_path}")
    except Exception as e:
        print(f"   ❌ Normalization failed: {e}")
        raise

    # 5) Load to graph (later)
    # upsert_to_graph(normalized)

    return {
        "paper_id": paper_id,
        "source": source,
        "parsed": str(parsed_path),
        "extracted": str(extracted_path),
        "validated": str(validated_path_to_use),
        "quality_report": str(quality_report_path),
        "normalized": str(normalized_path),
        "facts_extracted": len(triples),
        "facts_validated": len(valid_facts),
        "facts_normalized": len(normalized),
        "quality_score": avg_quality,
        "estimated_precision": precision,
        "status": "SUCCESS"
    }


def process_multiple_papers(
    sources: List[str],
    output_base: Path,
    quality_threshold: float = 0.70
) -> None:
    """Process multiple papers and generate summary report."""
    results: List[Dict] = []

    for i, source in enumerate(sources, 1):
        print(f"\n\n{'='*60}")
        print(f"🔄 Paper {i}/{len(sources)}")
        print(f"{'='*60}")

        try:
            result = process_single_paper(source, output_base, quality_threshold)
            results.append(result)
        except Exception as e:
            print(f"❌ Failed to process {source}: {e}")
            import traceback
            traceback.print_exc()

            if source.startswith('http'):
                import hashlib
                pid = hashlib.md5(source.encode()).hexdigest()[:12]
            else:
                pid = Path(source).stem

            results.append({
                "paper_id": pid,
                "source": source,
                "error": str(e),
                "status": "FAILED"
            })

    # Summary
    print(f"\n\n{'='*60}")
    print("📊 BATCH PROCESSING SUMMARY")
    print(f"{'='*60}\n")

    successful = [r for r in results if r.get("status") == "SUCCESS"]
    quality_failed = [r for r in results if r.get("status") == "QUALITY_GATE_FAILED"]
    failed = [r for r in results if r.get("status") == "FAILED"]

    print(f"✅ Successfully processed: {len(successful)}/{len(sources)}")
    print(f"⚠️  Quality gate failed: {len(quality_failed)}/{len(sources)}")
    print(f"❌ Processing failed: {len(failed)}/{len(sources)}")

    if successful:
        total_extracted = sum(r.get("facts_extracted", 0) for r in successful)
        total_validated = sum(r.get("facts_validated", 0) for r in successful)
        total_normalized = sum(r.get("facts_normalized", 0) for r in successful)

        print(f"\n📈 Total facts (successful papers):")
        print(f"   Extracted: {total_extracted}")
        print(f"   Validated: {total_validated}")
        print(f"   Normalized: {total_normalized}")

        precisions = [r.get("estimated_precision") for r in successful if r.get("estimated_precision") is not None]
        if precisions:
            avg_precision = sum(precisions) / len(precisions)
            print(f"\n📊 Average precision: {avg_precision:.1%}")

    if quality_failed:
        print(f"\n⚠️  Papers that failed quality gate:")
        for r in quality_failed:
            print(f"   - {r['paper_id']}: precision={r.get('estimated_precision', 0):.1%}")

    if failed:
        print(f"\n❌ Papers that failed processing:")
        for r in failed:
            print(f"   - {r['paper_id']}: {r.get('error', 'unknown error')}")

    summary_path = output_base / "reports" / "batch_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n💾 Summary report: {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Process papers through the full pipeline (parse → extract → validate → normalize)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", nargs="+", help="Path(s) to PDF file(s) or URL(s)")
    group.add_argument("--file", type=Path, help="Text file with one PDF path or URL per line")
    parser.add_argument("--output-base", type=Path, default=Path("data"), help="Base output directory (default: data)")
    parser.add_argument("--quality-threshold", type=float, default=0.95, help="Minimum precision to pass quality gate")
    parser.add_argument("--min-quality-score", type=int, default=None, help="Filter facts by min quality score (0–100) before normalization")
    args = parser.parse_args()

    # Collect sources
    if args.pdf:
        sources = args.pdf
        local_sources = [s for s in sources if not s.startswith('http')]
        missing = [s for s in local_sources if not Path(s).exists()]
        if missing:
            print("❌ The following local files were not found:")
            for p in missing:
                print(f"   - {p}")
            sys.exit(1)
    else:
        try:
            sources = load_papers_from_file(args.file)
            print(f"📋 Loaded {len(sources)} sources from {args.file}")
            local_sources = [s for s in sources if not s.startswith('http')]
            missing = [s for s in local_sources if not Path(s).exists()]
            if missing:
                print("⚠️  Warning: The following local files were not found:")
                for p in missing:
                    print(f"   - {p}")
                sources = [s for s in sources if s.startswith('http') or Path(s).exists()]
                print(f"📋 Proceeding with {len(sources)} valid sources")
        except FileNotFoundError as e:
            print(f"❌ {e}")
            sys.exit(1)

    if not sources:
        print("❌ No valid sources to process")
        sys.exit(1)

    output_base = args.output_base

    if len(sources) == 1:
        try:
            process_single_paper(
                sources[0],
                output_base,
                args.quality_threshold,
                min_quality_score=args.min_quality_score
            )
        except Exception as e:
            print(f"\n❌ Processing failed: {e}")
            sys.exit(1)
    else:
        process_multiple_papers(
            sources,
            output_base,
            args.quality_threshold
        )

if __name__ == "__main__":
    main()