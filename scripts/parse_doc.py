from pathlib import Path
import argparse, json
from src.core.ingest_docling import parse_document

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="data/raw_papers/WJCC-9-9350.pdf")
    ap.add_argument("--out", default="data/interim/sample_parsed.json")
    args = ap.parse_args()

    out = parse_document(args.source)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ Parsed: {args.source} → {args.out} | sections={len(out['sections'])}")

if __name__ == "__main__":
    main()
