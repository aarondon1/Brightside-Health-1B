#!/usr/bin/env python3
"""
Extract clinical facts from parsed documents using LLM.
Usage: python3 -m scripts.extract --input data/interim/sample_parsed.json --output data/processed/extracted/sample_facts.json
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.extract_llm import extract_pipeline

def main():
    parser = argparse.ArgumentParser(description="Extract clinical facts from parsed documents")
    parser.add_argument("--input", required=True, help="Path to parsed JSON file from Docling")
    parser.add_argument("--output", help="Path for extracted facts JSON output (auto-generated if not provided)")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use (default: gpt-4o-mini)")
    
    args = parser.parse_args()
    
    # Auto-generate output path if not provided
    if not args.output:
        input_path = Path(args.input)
        output_dir = Path("data/processed/extracted")
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = output_dir / f"{input_path.stem}_extracted.json"
    
    # Validate input file exists
    if not Path(args.input).exists():
        print(f"❌ Input file not found: {args.input}")
        print("💡 First run: python3 -m scripts.parse_doc --source <pdf> --out <parsed.json>")
        sys.exit(1)
    
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Please set OPENAI_API_KEY environment variable")
        print("💡 Option 1: export OPENAI_API_KEY=your_api_key_here")
        print("💡 Option 2: Add OPENAI_API_KEY=your_key to your .env file")
        sys.exit(1)
    
    print(f"🔍 Extracting facts from: {args.input}")
    print(f"📝 Output will be saved to: {args.output}")
    print(f"🤖 Using model: {args.model}")
    print("-" * 50)
    
    try:
        # Run extraction pipeline
        triples = extract_pipeline(args.input, args.output)
        
        print("-" * 50)
        print(f"✅ Extraction complete!")
        print(f"📊 Total facts extracted: {len(triples)}")
        print(f"💾 Results saved to: {args.output}")
        
        # Show summary by relation type
        if triples:
            relation_counts = {}
            for triple in triples:
                rel = triple.relation
                relation_counts[rel] = relation_counts.get(rel, 0) + 1
            
            print("\n📈 Facts by relation type:")
            for relation, count in sorted(relation_counts.items()):
                print(f"   {relation}: {count}")
                
        # Show next steps
        print(f"\n🎯 Next steps:")
        print(f"1. Review extracted facts: cat {args.output}")
        print(f"2. Run validation: python3 -m scripts.validate --input {args.output}")
        print(f"3. Run normalization: python3 -m scripts.normalize --input {args.output}")
    
    except KeyboardInterrupt:
        print("\n⏹ Extraction cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()