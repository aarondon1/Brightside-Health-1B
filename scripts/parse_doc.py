import argparse, json, sys, hashlib
from pathlib import Path

# Ensure project root on sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.ingest_docling import parse_document

def make_paper_id(source: str) -> str:
    s = str(source)
    if s.lower().startswith(("http://", "https://")):
        return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]
    return Path(s).stem

def main():
    ap = argparse.ArgumentParser(description="Parse a PDF/URL into sectioned JSON (Docling)")
    ap.add_argument("--source", required=True, help="Local PDF path or URL")
    ap.add_argument("--out", help="Output JSON path (default: data/interim/parsed/{paper_id}_parsed.json)")
    args = ap.parse_args()

    paper_id = make_paper_id(args.source)
    out_path = Path(args.out) if args.out else Path("data/interim/parsed") / f"{paper_id}_parsed.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = parse_document(args.source, source_id=paper_id)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ Parsed: {args.source} → {out_path} | sections={len(doc['sections'])}")
    print("\nNext:")
    print(f"  python -m scripts.extract --input \"{out_path}\"")

if __name__ == "__main__":
    main()