#!/usr/bin/env python3
"""
Extract clinical facts from parsed documents using LLM.
Usage: python -m scripts.extract --input data/interim/<paper>_parsed.json
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.extract_llm import extract_pipeline

def main():
    parser = argparse.ArgumentParser(description="Extract clinical facts from parsed documents")
    parser.add_argument("--input", required=True, help="Path to parsed JSON file from Docling")
    parser.add_argument("--output", help="Path for extracted facts JSON output (default: data/processed/extracted/{stem}_extracted.json)")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use (display only; pipeline uses configured default)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {args.input}")
        print("💡 First run: python -m scripts.parse_doc --source <pdf_or_url>")
        sys.exit(1)

    if not args.output:
        out_dir = Path("data/processed/extracted")
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output = out_dir / f"{input_path.stem}_extracted.json"

    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Please set OPENAI_API_KEY environment variable (.env supported)")
        sys.exit(1)

    print(f"🔍 Extracting facts from: {input_path}")
    print(f"📝 Output will be saved to: {args.output}")
    print(f"🤖 Using model: {args.model}")
    print("-" * 50)

    try:
        triples = extract_pipeline(input_path, args.output)
        print("-" * 50)
        print(f"✅ Extraction complete! {len(triples)} facts")
        print(f"💾 Saved: {args.output}")
        print("\nNext:")
        print(f"  python -m scripts.validate --input \"{args.output}\" --show-details")
    except KeyboardInterrupt:
        print("\n⏹ Extraction cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()