import streamlit as st
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import os

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import core functions (direct mode)
from src.core.ingest_docling import parse_document
from src.core.extract_llm import extract_pipeline
from src.core.validate import validate_extracted_facts, save_validation_results
from src.core.normalize_ontology import OntologyNormalizer


def check_neo4j_connection(uri: str, user: str, password: str) -> tuple[bool, str]:
    """Test Neo4j connection and return status."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True, "✅ Connected"
    except Exception as e:
        return False, f"❌ Connection failed: {str(e)}"
    
# Page config
st.set_page_config(
    page_title="Brightside Health AI Studio",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'current_paper' not in st.session_state:
    st.session_state.current_paper = None
if 'pipeline_state' not in st.session_state:
    st.session_state.pipeline_state = {
        'parsed': False,
        'extracted': False,
        'validated': False,
        'quality_checked': False,
        'normalized': False,
        'loaded_to_graph': False
    }
if 'paper_data' not in st.session_state:
    st.session_state.paper_data = {}
if 'execution_mode' not in st.session_state:
    st.session_state.execution_mode = 'direct'  # 'direct' or 'subprocess'
if 'default_quality_methods' not in st.session_state:
    st.session_state.default_quality_methods = ['heuristic']

if 'neo4j_uri' not in st.session_state:
    st.session_state.neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
if 'neo4j_user' not in st.session_state:
    st.session_state.neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
if 'neo4j_password' not in st.session_state:
    st.session_state.neo4j_password = os.getenv('NEO4J_PASSWORD', '')

# Utility functions
def reset_pipeline():
    """Reset pipeline state for new paper."""
    st.session_state.pipeline_state = {
        'parsed': False,
        'extracted': False,
        'validated': False,
        'quality_checked': False,
        'normalized': False,
        'loaded_to_graph': False
    }
    st.session_state.paper_data = {}

def get_file_size(path: Path) -> str:
    """Get human-readable file size."""
    if not path.exists():
        return "N/A"
    size = path.stat().st_size
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def load_json_safe(path: Path) -> Optional[Dict]:
    """Safely load JSON file."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        st.error(f"Error loading {path}: {e}")
    return None

def run_script_subprocess(script_name: str, args: List[str]) -> tuple[int, str, str]:
    """Run a script using subprocess and capture output."""
    cmd = [sys.executable, f"scripts/{script_name}.py"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
    return result.returncode, result.stdout, result.stderr

# Header
st.title("🧠 Brightside Health AI Studio")
st.markdown("**Clinical Knowledge Graph Pipeline — Human-in-the-Loop**")
st.markdown("---")

# Sidebar - Paper Selection & Settings
with st.sidebar:
    # Quick setup guide
    with st.expander("⚡ Quick Setup Guide"):
        st.markdown("""
        **First Time Setup:**
        
        1. **Install Neo4j**
           - Desktop: https://neo4j.com/download/
           - Or Docker: `docker run -p 7474:7474 -p 7687:7687 neo4j:5.15`
        
        2. **Start Database**
           - Neo4j Desktop: Create → Start
           - Docker: Container auto-starts
        
        3. **Configure Connection**
           - Scroll down to "Neo4j Database"
           - Enter URI (default: bolt://localhost:7687)
           - Enter username (default: neo4j)
           - Enter password (set during installation)
           - Click "Test Connection"
        
        4. **Set Environment**
           - Edit `.env` file with your credentials
           - Restart Streamlit if credentials change
        
        5. **Select Paper**
           - Upload PDF, enter URL, or select existing
           - Run through pipeline stages
        """)
    
    st.markdown("---")
 
    st.header("📄 Paper Input")
    
    # Execution mode toggle
    st.session_state.execution_mode = st.radio(
        "Execution Mode",
        ["direct", "subprocess"],
        format_func=lambda x: "Direct (Fast)" if x == "direct" else "Subprocess (Isolated)",
        help="Direct mode imports functions, subprocess mode runs scripts in separate processes"
    )
    
    st.markdown("---")
    
    input_method = st.radio(
        "Input Method",
        ["Upload PDF", "Enter URL", "Select from data/raw_papers"]
    )
    
    paper_source = None
    paper_id = None
    
    if input_method == "Upload PDF":
        uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])
        if uploaded_file:
            temp_dir = Path("data/raw_papers/uploaded")
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / uploaded_file.name
            
            # Save uploaded file
            if st.button("💾 Save Uploaded File"):
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success(f"Saved to: {temp_path}")
                paper_source = str(temp_path)
                paper_id = temp_path.stem
                reset_pipeline()
                st.session_state.current_paper = paper_id
    
    elif input_method == "Enter URL":
        url = st.text_input("Paper URL (PubMed, arXiv, etc.)")
        if url and st.button("🔗 Use URL"):
            import hashlib
            paper_source = url
            paper_id = hashlib.md5(url.encode()).hexdigest()[:12]
            reset_pipeline()
            st.session_state.current_paper = paper_id
    
    else:  # Select from data/raw_papers
        raw_papers_dir = Path("data/raw_papers")
        if raw_papers_dir.exists():
            pdf_files = list(raw_papers_dir.glob("**/*.pdf"))
            if pdf_files:
                selected_file = st.selectbox(
                    "Select PDF",
                    pdf_files,
                    format_func=lambda x: x.name
                )
                if st.button("📂 Use Selected File"):
                    paper_source = str(selected_file)
                    paper_id = selected_file.stem
                    reset_pipeline()
                    st.session_state.current_paper = paper_id
            else:
                st.warning("No PDFs found in data/raw_papers/")
        else:
            st.warning("data/raw_papers/ directory not found")
    
    st.markdown("---")
    
    # Current paper info
    if st.session_state.current_paper:
        st.success(f"📄 **Current Paper:** {st.session_state.current_paper}")
        if st.button("🔄 Reset Pipeline"):
            reset_pipeline()
            st.rerun()
    else:
        st.info("No paper selected")
    
    st.markdown("---")
    
    # Pipeline Settings
    st.header("⚙️ Pipeline Settings")
    quality_threshold = st.slider(
        "Quality Threshold (%)",
        min_value=70,
        max_value=99,
        value=95,
        help="Minimum precision to pass quality gate"
    ) / 100
    
    min_quality_score = st.slider(
        "Min Fact Quality Score",
        min_value=0,
        max_value=100,
        value=0,
        help="Filter facts by quality score (0 = no filter)"
    )
    
    if min_quality_score == 0:
        min_quality_score = None
    
    min_fuzzy_score = st.slider(
        "Min Fuzzy Match Score",
        min_value=0.7,
        max_value=1.0,
        value=0.86,
        step=0.01,
        help="Minimum similarity for ontology matching"
    )
    
    # In the sidebar, after Pipeline Settings (around line 210)

    st.markdown("---")
    
    # Neo4j Configuration
    st.header("Neo4j Database")
    
    with st.expander("Database Connection", expanded=False):
        st.markdown("""
        **Setup Instructions:**
        1. Install Neo4j Desktop or use Docker
        2. Create a new database
        3. Start the database instance
        4. Note the Bolt URI (default: bolt://localhost:7687)
        5. Note username (default: neo4j)
        6. Set a password
        """)
        
        st.session_state.neo4j_uri = st.text_input(
            "Neo4j URI",
            value=st.session_state.neo4j_uri,
            help="Bolt protocol URI (e.g., bolt://localhost:7687)"
        )
        
        st.session_state.neo4j_user = st.text_input(
            "Username",
            value=st.session_state.neo4j_user
        )
        
        st.session_state.neo4j_password = st.text_input(
            "Password",
            value=st.session_state.neo4j_password,
            type="password"
        )
        
        if st.button("🔌 Test Connection"):
            with st.spinner("Testing connection..."):
                is_connected, message = check_neo4j_connection(
                    st.session_state.neo4j_uri,
                    st.session_state.neo4j_user,
                    st.session_state.neo4j_password
                )
                if is_connected:
                    st.success(message)
                    st.session_state.neo4j_connected = True
                else:
                    st.error(message)
                    st.session_state.neo4j_connected = False
        
        # Connection status indicator
        if st.session_state.get('neo4j_connected'):
            st.success("🟢 Database Connected")
        else:
            st.warning("🔴 Database Not Connected")
    
    st.markdown("---")
    
    # Quality Assessment Methods
    st.header("📊 Quality Assessment")
    
    default_methods = st.multiselect(
        "Default Assessment Methods",
        options=["heuristic", "nli", "llm_judge", "knowledge_base"],
        default=st.session_state.default_quality_methods,
        help="""
        Select which methods to use by default:
        • **heuristic**: Fast rule-based checks (FREE)
        • **nli**: Semantic similarity (requires sentence-transformers)
        • **llm_judge**: GPT-4o verification (COSTS API CALLS ~$0.001/fact)
        • **knowledge_base**: Cross-reference known facts
        
        You can override this for each paper in Stage 4.
        """
    )
    
    st.session_state.default_quality_methods = default_methods
    
    # Show cost estimate if LLM selected
    if "llm_judge" in default_methods:
        st.caption("💰 LLM Judge: ~$0.001-0.002 per fact")

# Main content - Pipeline Stages
if not st.session_state.current_paper:
    st.info("👈 Select a paper from the sidebar to begin")
    
    # Pipeline overview
    st.markdown("""
    ### 📋 Pipeline Overview
    
    This system processes medical papers through 6 stages:
    
    1. **Parse** - Extract structured text from PDF/URL using Docling
    2. **Extract** - Use GPT-4o to extract clinical facts as JSON triples
    3. **Validate** - Check facts against schema and logical rules
    4. **Quality Check** - Assess precision using multiple methods (heuristic, NLI, LLM judge)
    5. **Normalize** - Map terms to standard ontology codes (RxNorm, SNOMED)
    6. **Load to Graph** - Insert into Neo4j knowledge graph
    
    Each stage requires **manual approval** to proceed, giving you full control.
    """)
    
    # Show script mapping
    st.markdown("### 🔧 Script Mapping")
    script_map = {
        "Parse": "scripts/parse_doc.py",
        "Extract": "scripts/extract.py",
        "Validate": "scripts/validate.py",
        "Quality": "scripts/auto_validate_quality.py",
        "Normalize": "scripts/normalize.py",
        "Load": "scripts/load_neo4j.py"
    }
    
    for stage, script in script_map.items():
        st.code(f"{stage:12} → {script}", language="text")
    
    # Quality Assessment Methods Info
    st.markdown("### 📊 Quality Assessment Methods")
    
    with st.expander("Method Comparison"):
        comparison_data = {
            "Method": ["Heuristic", "NLI", "LLM Judge", "Knowledge Base"],
            "Speed": ["⚡ Fast", "🐢 Slow", "🐌 Very Slow", "⚡ Fast"],
            "Cost": ["FREE", "FREE", "$$$ (~$0.001/fact)", "FREE"],
            "Accuracy": ["Good (70-80%)", "Very Good (80-90%)", "Excellent (90-95%)", "Perfect (100% on known)"],
            "Dependencies": ["None", "sentence-transformers", "OpenAI API", "Curated database"],
            "Use Case": ["Default", "Semantic validation", "High-stakes verification", "Cross-reference check"]
        }
        df = pd.DataFrame(comparison_data)
        st.dataframe(df, use_container_width=True)
    
    with st.expander("How Quality Assessment Works"):
        st.markdown("""
        **Quality Assessment combines multiple validation methods:**
        
        **1. Heuristic (Rule-Based)**
        - Checks if drug appears in span (strict)
        - Checks if condition appears in span (lenient)
        - Validates relation keywords
        - Checks confidence alignment
        - Validates span completeness
        
        **2. NLI (Semantic Similarity)**
        - Constructs claim from fact
        - Computes embedding similarity
        - Checks if span supports claim
        
        **3. LLM Judge (GPT-4o Verification)**
        - Uses GPT-4o to verify each fact
        - Most accurate but expensive
        - Best for final validation
        
        **4. Knowledge Base (Cross-Reference)**
        - Checks against known drug-condition pairs
        - Perfect accuracy on known facts
        - Limited coverage
        
        **Combining Methods:**
        - Quality scores are averaged
        - Correctness uses majority vote
        - More methods = higher confidence
        """)

else:
    paper_id = st.session_state.current_paper
    
    # Pipeline progress bar
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        if st.session_state.pipeline_state['parsed']:
            st.success("✅ Parsed")
        else:
            st.warning("⏳ Parse")
    
    with col2:
        if st.session_state.pipeline_state['extracted']:
            st.success("✅ Extracted")
        else:
            st.warning("⏳ Extract")
    
    with col3:
        if st.session_state.pipeline_state['validated']:
            st.success("✅ Validated")
        else:
            st.warning("⏳ Validate")
    
    with col4:
        if st.session_state.pipeline_state['quality_checked']:
            st.success("✅ Quality")
        else:
            st.warning("⏳ Quality")
    
    with col5:
        if st.session_state.pipeline_state['normalized']:
            st.success("✅ Normalized")
        else:
            st.warning("⏳ Normalize")
    
    with col6:
        if st.session_state.pipeline_state['loaded_to_graph']:
            st.success("✅ Loaded")
        else:
            st.info("⏳ Load to Graph")
    
    st.markdown("---")
    
    # Stage 1: Parse
    with st.expander("**1️⃣ Parse Document**", expanded=not st.session_state.pipeline_state['parsed']):
        st.markdown("""
        **Purpose:** Convert PDF/URL into structured JSON with sections and sentence spans.
        
        **Script:** `scripts/parse_doc.py`
        
        **Output:** `data/interim/{paper_id}_parsed.json`
        """)
        
        parsed_path = Path("data/interim") / f"{paper_id}_parsed.json"
        
        if st.session_state.pipeline_state['parsed']:
            st.success("✅ Already parsed")
            if parsed_path.exists():
                st.info(f"📁 File: {parsed_path} ({get_file_size(parsed_path)})")
                
                # Show preview
                parsed_data = load_json_safe(parsed_path)
                if parsed_data:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Source ID", parsed_data.get("metadata", {}).get("source_id", "N/A"))
                    with col2:
                        st.metric("Sections", len(parsed_data.get("sections", [])))
                    with col3:
                        st.metric("Text Length", len(parsed_data.get("full_text", "")))
                    
                    with st.expander("Preview Sections"):
                        sections = parsed_data.get("sections", [])
                        for i, section in enumerate(sections[:5], 1):
                            st.markdown(f"**{i}. {section.get('name')}** ({len(section.get('text', ''))} chars)")
                            st.caption(section.get('text', '')[:200] + "...")
        else:
            # Show command that will be run
            if st.session_state.execution_mode == 'subprocess':
                st.code(f"python scripts/parse_doc.py --source \"{paper_source or 'TBD'}\" --out \"{parsed_path}\"", language="bash")
            
            if st.button("▶️ Run Parse", key="parse_btn"):
                with st.spinner("Parsing document..."):
                    try:
                        # Get paper source
                        if paper_source:
                            src = paper_source
                        else:
                            # Try to find in raw_papers
                            possible_paths = [
                                Path("data/raw_papers") / f"{paper_id}.pdf",
                                Path("data/raw_papers/uploaded") / f"{paper_id}.pdf"
                            ]
                            src = next((str(p) for p in possible_paths if p.exists()), None)
                            if not src:
                                st.error(f"Could not find source for paper_id: {paper_id}")
                                st.stop()
                        
                        if st.session_state.execution_mode == 'direct':
                            # Direct mode: import and call function
                            parsed_doc = parse_document(src, source_id=paper_id)
                            parsed_path.parent.mkdir(parents=True, exist_ok=True)
                            parsed_path.write_text(json.dumps(parsed_doc, indent=2), encoding='utf-8')
                            st.success("✅ Parse complete (direct mode)!")
                        else:
                            # Subprocess mode: run script
                            returncode, stdout, stderr = run_script_subprocess(
                                "parse_doc",
                                ["--source", src, "--out", str(parsed_path)]
                            )
                            
                            if returncode == 0:
                                st.success("✅ Parse complete (subprocess mode)!")
                                with st.expander("Show output"):
                                    st.code(stdout)
                            else:
                                st.error(f"❌ Parse failed (exit code {returncode})")
                                with st.expander("Show error"):
                                    st.code(stderr)
                                st.stop()
                        
                        # Update state
                        st.session_state.pipeline_state['parsed'] = True
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Parse failed: {e}")
                        import traceback
                        st.code(traceback.format_exc())
    
    # Stage 2: Extract
    with st.expander("**2️⃣ Extract Facts (LLM)**", expanded=st.session_state.pipeline_state['parsed'] and not st.session_state.pipeline_state['extracted']):
        st.markdown("""
        **Purpose:** Use GPT-4o to extract clinical facts (drug-condition-relation triples).
        
        **Script:** `scripts/extract.py`
        
        **Output:** `data/processed/extracted/{paper_id}_extracted.json`
        """)
        
        if not st.session_state.pipeline_state['parsed']:
            st.warning("⚠️ Complete Parse step first")
        else:
            extracted_path = Path("data/processed/extracted") / f"{paper_id}_extracted.json"
            
            if st.session_state.pipeline_state['extracted']:
                st.success("✅ Already extracted")
                if extracted_path.exists():
                    st.info(f"📁 File: {extracted_path} ({get_file_size(extracted_path)})")
                    
                    # Show preview
                    extracted_data = load_json_safe(extracted_path)
                    if extracted_data:
                        facts = extracted_data.get("extracted_facts", [])
                        st.metric("Facts Extracted", len(facts))
                        
                        with st.expander("Preview Facts"):
                            if facts:
                                df = pd.DataFrame(facts[:10])
                                # NEW: Show new clinical fields if present
                                display_cols = ['drug_name', 'condition_name', 'relation', 'confidence']
                                optional_cols = ['treatment_line', 'patient_subgroup', 'sample_size', 'study_design']
                                available_cols = [c for c in (display_cols + optional_cols) if c in df.columns]
                                st.dataframe(df[available_cols] if available_cols else df)
            else:
                # Show command
                if st.session_state.execution_mode == 'subprocess':
                    st.code(f"python scripts/extract.py --input \"{Path('data/interim') / f'{paper_id}_parsed.json'}\" --output \"{extracted_path}\"", language="bash")
                
                if st.button("▶️ Run Extract", key="extract_btn"):
                    with st.spinner("Extracting facts (this may take a few minutes)..."):
                        try:
                            parsed_path = Path("data/interim") / f"{paper_id}_parsed.json"
                            
                            if st.session_state.execution_mode == 'direct':
                                triples = extract_pipeline(parsed_path, extracted_path)
                                st.success(f"✅ Extracted {len(triples)} facts (direct mode)!")
                            else:
                                returncode, stdout, stderr = run_script_subprocess(
                                    "extract",
                                    ["--input", str(parsed_path), "--output", str(extracted_path)]
                                )
                                
                                if returncode == 0:
                                    st.success("✅ Extract complete (subprocess mode)!")
                                    with st.expander("Show output"):
                                        st.code(stdout)
                                else:
                                    st.error(f"❌ Extract failed (exit code {returncode})")
                                    with st.expander("Show error"):
                                        st.code(stderr)
                                    st.stop()
                            
                            st.session_state.pipeline_state['extracted'] = True
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Extract failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
    
    # Stage 3: Validate
    with st.expander("**3️⃣ Validate Facts**", expanded=st.session_state.pipeline_state['extracted'] and not st.session_state.pipeline_state['validated']):
        st.markdown("""
        **Purpose:** Check facts against schema rules and filter invalid/suspicious items.
        
        **Script:** `scripts/validate.py`
        
        **Output:** `data/processed/validated/{paper_id}_validated.json`
        """)
        
        if not st.session_state.pipeline_state['extracted']:
            st.warning("⚠️ Complete Extract step first")
        else:
            validated_path = Path("data/processed/validated") / f"{paper_id}_validated.json"
            issues_path = Path("data/processed/validated") / f"{paper_id}_issues.json"
            
            if st.session_state.pipeline_state['validated']:
                st.success("✅ Already validated")
                if validated_path.exists():
                    st.info(f"📁 File: {validated_path} ({get_file_size(validated_path)})")
                    
                    # Show stats
                    validated_data = load_json_safe(validated_path)
                    if validated_data:
                        facts = validated_data.get("validated_facts", [])
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Valid Facts", len(facts))
                        with col2:
                            issues_data = load_json_safe(issues_path)
                            if issues_data:
                                st.metric("Issues Found", len(issues_data.get("issues", [])))
                        
                        with st.expander("View Issues"):
                            if issues_data and issues_data.get("issues"):
                                issues_df = pd.DataFrame(issues_data["issues"])
                                st.dataframe(issues_df)
            else:
                # Show command
                if st.session_state.execution_mode == 'subprocess':
                    st.code(f"python scripts/validate.py --input \"{Path('data/processed/extracted') / f'{paper_id}_extracted.json'}\" --output \"{validated_path}\" --issues \"{issues_path}\"", language="bash")
                
                if st.button("▶️ Run Validate", key="validate_btn"):
                    with st.spinner("Validating facts..."):
                        try:
                            extracted_path = Path("data/processed/extracted") / f"{paper_id}_extracted.json"
                            
                            if st.session_state.execution_mode == 'direct':
                                facts_data = json.loads(extracted_path.read_text(encoding='utf-8'))
                                valid_facts, report = validate_extracted_facts(facts_data)
                                
                                validated_path.parent.mkdir(parents=True, exist_ok=True)
                                save_validation_results(valid_facts, report, validated_path, issues_path)
                                
                                st.success(f"✅ Validated {len(valid_facts)}/{report.total_facts} facts (direct mode)!")
                            else:
                                returncode, stdout, stderr = run_script_subprocess(
                                    "validate",
                                    ["--input", str(extracted_path), "--output", str(validated_path), "--issues", str(issues_path)]
                                )
                                
                                if returncode == 0:
                                    st.success("✅ Validate complete (subprocess mode)!")
                                    with st.expander("Show output"):
                                        st.code(stdout)
                                else:
                                    st.error(f"❌ Validate failed (exit code {returncode})")
                                    with st.expander("Show error"):
                                        st.code(stderr)
                                    st.stop()
                            
                            st.session_state.pipeline_state['validated'] = True
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Validate failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
    
    # Stage 4: Quality Check
    with st.expander("**4️⃣ Quality Assessment**", expanded=st.session_state.pipeline_state['validated'] and not st.session_state.pipeline_state['quality_checked']):
        st.markdown(f"""
        **Purpose:** Estimate precision using multiple validation methods.
        
        **Script:** `scripts/auto_validate_quality.py`
        
        **Output:** `data/eval/{paper_id}_quality_report.json`
        """)
        
        if not st.session_state.pipeline_state['validated']:
            st.warning("⚠️ Complete Validate step first")
        else:
            quality_report_path = Path("data/eval") / f"{paper_id}_quality_report.json"
            
            if st.session_state.pipeline_state['quality_checked']:
                st.success("✅ Already checked")
                if quality_report_path.exists():
                    st.info(f"📁 File: {quality_report_path} ({get_file_size(quality_report_path)})")
                    
                    # Show stats
                    quality_data = load_json_safe(quality_report_path)
                    if quality_data:
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Facts", quality_data.get("total_facts", 0))
                        with col2:
                            st.metric("Avg Quality Score", f"{quality_data.get('average_quality_score', 0):.1f}/100")
                        with col3:
                            precision = quality_data.get("estimated_precision", 0)
                            st.metric("Estimated Precision", f"{precision:.1%}")
                            
                            if precision < quality_threshold:
                                st.error("⚠️ Below threshold!")
                            else:
                                st.success("✅ Passed!")
                        
                        # Show which methods were used
                        with st.expander("Method Details"):
                            if "results" in quality_data and len(quality_data["results"]) > 0:
                                first_result = quality_data["results"][0]
                                methods_used = list(first_result.get("method_results", {}).keys())
                                st.write(f"**Methods used:** {', '.join(methods_used)}")
                                
                                # Show per-method results for first fact as example
                                st.json(first_result.get("method_results", {}))
            else:
                # Method selection UI
                st.markdown("### Select Assessment Methods")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    use_heuristic = st.checkbox(
                        "🔍 Heuristic (Fast, Free)",
                        value="heuristic" in st.session_state.default_quality_methods,
                        help="Rule-based checks: drug in span, relation keywords, confidence"
                    )
                    use_nli = st.checkbox(
                        "🧠 NLI Similarity",
                        value="nli" in st.session_state.default_quality_methods,
                        help="Semantic similarity using sentence-transformers (requires library)"
                    )
                
                with col2:
                    use_llm = st.checkbox(
                        "🤖 LLM Judge (Accurate, Costs $$)",
                        value="llm_judge" in st.session_state.default_quality_methods,
                        help="Use GPT-4o to verify each fact"
                    )
                    use_kb = st.checkbox(
                        "📚 Knowledge Base",
                        value="knowledge_base" in st.session_state.default_quality_methods,
                        help="Cross-reference against known drug-condition pairs"
                    )
                
                # Build methods list
                selected_methods = []
                if use_heuristic:
                    selected_methods.append("heuristic")
                if use_nli:
                    selected_methods.append("nli")
                if use_llm:
                    selected_methods.append("llm_judge")
                if use_kb:
                    selected_methods.append("knowledge_base")
                
                if not selected_methods:
                    st.error("⚠️ Please select at least one assessment method")
                else:
                    st.info(f"**Selected methods:** {', '.join(selected_methods)}")
                    
                    # Cost warning for LLM judge
                    if "llm_judge" in selected_methods:
                        validated_path = Path("data/processed/validated") / f"{paper_id}_validated.json"
                        if validated_path.exists():
                            validated_data = load_json_safe(validated_path)
                            if validated_data:
                                fact_count = len(validated_data.get("validated_facts", []))
                                estimated_cost = (fact_count / 10) * 0.01  # Rough estimate
                                st.warning(f"⚠️ LLM Judge will verify {fact_count} facts. Estimated cost: ~${estimated_cost:.2f}")
                
                # Show command
                if st.session_state.execution_mode == 'subprocess' and selected_methods:
                    methods_arg = " ".join(selected_methods)
                    st.code(f"python scripts/auto_validate_quality.py --input \"{Path('data/processed/validated') / f'{paper_id}_validated.json'}\" --output \"{quality_report_path}\" --methods {methods_arg}", language="bash")
                
                if st.button("▶️ Run Quality Check", key="quality_btn", disabled=not selected_methods):
                    with st.spinner(f"Assessing quality using {len(selected_methods)} method(s)..."):
                        try:
                            validated_path = Path("data/processed/validated") / f"{paper_id}_validated.json"
                            
                            if st.session_state.execution_mode == 'direct':
                                from scripts.auto_validate_quality import assess_dataset_quality
                                
                                validated_data = json.loads(validated_path.read_text(encoding='utf-8'))
                                facts = validated_data.get("validated_facts", [])
                                
                                st.info(f"📊 Assessing {len(facts)} facts with methods: {', '.join(selected_methods)}")
                                
                                # Progress bar for LLM judge
                                if "llm_judge" in selected_methods:
                                    st.warning("⏳ LLM Judge is running... This may take several minutes.")
                                
                                # Run assessment with selected methods
                                quality_report = assess_dataset_quality(facts, methods=selected_methods)
                                
                                quality_report_path.parent.mkdir(parents=True, exist_ok=True)
                                quality_report_path.write_text(json.dumps(quality_report, indent=2), encoding='utf-8')
                                
                                precision = quality_report.get("estimated_precision", 0)
                                avg_quality = quality_report.get("average_quality_score", 0)
                                
                                st.success(f"✅ Quality: {avg_quality:.1f}/100, Precision: {precision:.1%}")
                                st.info(f"Methods used: {', '.join(selected_methods)}")
                                
                                if precision < quality_threshold:
                                    st.warning(f"⚠️ Precision {precision:.1%} < threshold {quality_threshold:.1%}")
                                    st.info("💡 Consider adjusting settings or reviewing extraction prompts")
                            else:
                                # Subprocess mode
                                methods_args = []
                                for method in selected_methods:
                                    methods_args.extend(["--methods", method])
                                
                                returncode, stdout, stderr = run_script_subprocess(
                                    "auto_validate_quality",
                                    ["--input", str(validated_path), "--output", str(quality_report_path)] + methods_args
                                )
                                
                                if returncode == 0:
                                    st.success("✅ Quality check complete (subprocess mode)!")
                                    with st.expander("Show output"):
                                        st.code(stdout)
                                else:
                                    st.error(f"❌ Quality check failed (exit code {returncode})")
                                    with st.expander("Show error"):
                                        st.code(stderr)
                                    st.stop()
                            
                            st.session_state.pipeline_state['quality_checked'] = True
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Quality check failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
    
    # Stage 5: Normalize
    with st.expander("**5️⃣ Normalize to Ontologies**", expanded=st.session_state.pipeline_state['quality_checked'] and not st.session_state.pipeline_state['normalized']):
        st.markdown("""
        **Purpose:** Map drug/condition names to standard codes (RxNorm, SNOMED CT).
        
        **Script:** `scripts/normalize.py`
        
        **Output:** `data/processed/normalized/{paper_id}_normalized.json`
        """)
        
        if not st.session_state.pipeline_state['quality_checked']:
            st.warning("⚠️ Complete Quality Check step first")
        else:
            normalized_path = Path("data/processed/normalized") / f"{paper_id}_normalized.json"
            
            if st.session_state.pipeline_state['normalized']:
                st.success("✅ Already normalized")
                if normalized_path.exists():
                    st.info(f"📁 File: {normalized_path} ({get_file_size(normalized_path)})")
                    
                    # Show stats
                    normalized_data = load_json_safe(normalized_path)
                    if normalized_data:
                        facts = normalized_data.get("normalized_facts", [])
                        st.metric("Normalized Facts", len(facts))
                        
                        # Match statistics
                        matched = sum(1 for f in facts if f.get('drug', {}).get('match_type') != 'unmatched')
                        total = len(facts)
                        match_rate = matched / total if total > 0 else 0
                        
                        st.progress(match_rate)
                        st.caption(f"Mapping coverage: {matched}/{total} ({match_rate*100:.1f}%)")
                        
                        # Show unmatched button
                        if total - matched > 0:
                            if st.button("🔍 Show Unmatched Items"):
                                st.info("Run: `python scripts/show_unmatched_normalized.py --input " + str(normalized_path) + "`")
            else:
                # Show command
                if st.session_state.execution_mode == 'subprocess':
                    st.code(f"python scripts/normalize.py --input \"{Path('data/processed/validated') / f'{paper_id}_validated.json'}\" --output \"{normalized_path}\" --min-fuzzy-score {min_fuzzy_score}", language="bash")
                
                if st.button("▶️ Run Normalize", key="normalize_btn"):
                    with st.spinner("Normalizing to ontologies..."):
                        try:
                            validated_path = Path("data/processed/validated") / f"{paper_id}_validated.json"
                            
                            if st.session_state.execution_mode == 'direct':
                                normalizer = OntologyNormalizer(
                                    config_path="configs/mappings.yaml",
                                    min_fuzzy_score=min_fuzzy_score
                                )
                                normalized = normalizer.normalize_file(validated_path)
                                
                                normalized_path.parent.mkdir(parents=True, exist_ok=True)
                                payload = {"normalized_facts": [fact.model_dump() for fact in normalized]}
                                normalized_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
                                
                                st.success(f"✅ Normalized {len(normalized)} facts (direct mode)!")
                            else:
                                returncode, stdout, stderr = run_script_subprocess(
                                    "normalize",
                                    ["--input", str(validated_path), "--output", str(normalized_path), "--min-fuzzy-score", str(min_fuzzy_score)]
                                )
                                
                                if returncode == 0:
                                    st.success("✅ Normalize complete (subprocess mode)!")
                                    with st.expander("Show output"):
                                        st.code(stdout)
                                else:
                                    st.error(f"❌ Normalize failed (exit code {returncode})")
                                    with st.expander("Show error"):
                                        st.code(stderr)
                                    st.stop()
                            
                            st.session_state.pipeline_state['normalized'] = True
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Normalize failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
    
    # Stage 6: Load to Graph
    with st.expander("**6️⃣ Load to Knowledge Graph**", expanded=st.session_state.pipeline_state['normalized'] and not st.session_state.pipeline_state['loaded_to_graph']):
        st.markdown("""
        **Purpose:** Insert normalized facts into Neo4j graph database.
        
        **Script:** `scripts/load_neo4j.py`
        
        **Output:** Knowledge graph with nodes and relationships
        """)
        
        if not st.session_state.pipeline_state['normalized']:
            st.warning("⚠️ Complete Normalize step first")
        else:
            normalized_path = Path("data/processed/normalized") / f"{paper_id}_normalized.json"
            
            # Check if already loaded
            if st.session_state.pipeline_state['loaded_to_graph']:
                st.success("✅ Already loaded to graph")
                
                # Show graph statistics
                if st.button("📊 Show Graph Statistics"):
                    try:
                        from neo4j import GraphDatabase
                        driver = GraphDatabase.driver(
                            st.session_state.neo4j_uri,
                            auth=(st.session_state.neo4j_user, st.session_state.neo4j_password)
                        )
                        
                        with driver.session() as session:
                            # Node counts
                            result = session.run("""
                                MATCH (n)
                                RETURN labels(n)[0] AS label, count(n) AS count
                                ORDER BY count DESC
                            """)
                            node_stats = [{"Label": r["label"], "Count": r["count"]} for r in result]
                            
                            # Relationship counts
                            result = session.run("""
                                MATCH ()-[r]->()
                                RETURN type(r) AS type, count(r) AS count
                                ORDER BY count DESC
                            """)
                            rel_stats = [{"Type": r["type"], "Count": r["count"]} for r in result]
                        
                        driver.close()
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**Nodes:**")
                            st.dataframe(pd.DataFrame(node_stats), use_container_width=True)
                        with col2:
                            st.markdown("**Relationships:**")
                            st.dataframe(pd.DataFrame(rel_stats), use_container_width=True)
                    
                    except Exception as e:
                        st.error(f"Failed to fetch statistics: {e}")
            
            else:
                # Pre-flight checks
                st.markdown("### Pre-Flight Checks")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Check 1: Normalized file exists
                    if normalized_path.exists():
                        st.success(f"✅ Normalized file ready ({get_file_size(normalized_path)})")
                    else:
                        st.error("❌ Normalized file not found")
                
                with col2:
                    # Check 2: Neo4j connection
                    if st.session_state.get('neo4j_connected'):
                        st.success("✅ Neo4j connected")
                    else:
                        st.error("❌ Neo4j not connected")
                        st.info("Configure connection in sidebar")
                
                # Load options
                st.markdown("### Load Options")
                
                clear_existing = st.checkbox(
                    "🗑️ Clear existing graph data before loading",
                    value=False,
                    help="WARNING: This will delete ALL data in the Neo4j database"
                )
                
                if clear_existing:
                    st.warning("⚠️ This will DELETE all existing nodes and relationships!")
                
                # Show command that will be run
                if st.session_state.execution_mode == 'subprocess':
                    cmd = f"python scripts/load_neo4j.py --input \"{normalized_path}\""
                    if clear_existing:
                        cmd += " --clear"
                    cmd += f" --uri \"{st.session_state.neo4j_uri}\" --user \"{st.session_state.neo4j_user}\" --password \"***\""
                    st.code(cmd, language="bash")
                
                # Load button (only enabled if checks pass)
                can_load = (
                    normalized_path.exists() and
                    st.session_state.get('neo4j_connected', False)
                )
                
                if not can_load:
                    st.warning("⚠️ Complete pre-flight checks before loading")
                
                if st.button("▶️ Load to Graph", key="load_btn", disabled=not can_load):
                    with st.spinner("Loading facts into Neo4j..."):
                        try:
                            if st.session_state.execution_mode == 'direct':
                                # Direct mode: import and call function
                                from scripts.load_neo4j import Neo4jLoader, load_normalized_data
                                
                                loader = Neo4jLoader(
                                    st.session_state.neo4j_uri,
                                    st.session_state.neo4j_user,
                                    st.session_state.neo4j_password
                                )
                                
                                # Clear if requested
                                if clear_existing:
                                    with st.spinner("Clearing existing data..."):
                                        loader.clear_database()
                                        st.info("🗑️ Database cleared")
                                
                                # Load normalized data
                                progress_placeholder = st.empty()
                                progress_placeholder.info("📊 Loading normalized facts...")
                                
                                load_normalized_data(loader, str(normalized_path))
                                
                                # Get summary statistics
                                with loader.driver.session() as session:
                                    node_count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
                                    rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
                                
                                loader.close()
                                
                                progress_placeholder.empty()
                                st.success(f"✅ Load complete! {node_count} nodes, {rel_count} relationships (direct mode)")
                            
                            else:
                                # Subprocess mode: run script
                                args = [
                                    "--input", str(normalized_path),
                                    "--uri", st.session_state.neo4j_uri,
                                    "--user", st.session_state.neo4j_user,
                                    "--password", st.session_state.neo4j_password
                                ]
                                
                                if clear_existing:
                                    args.append("--clear")
                                
                                returncode, stdout, stderr = run_script_subprocess("load_neo4j", args)
                                
                                if returncode == 0:
                                    st.success("✅ Load complete (subprocess mode)!")
                                    with st.expander("Show output"):
                                        st.code(stdout)
                                else:
                                    st.error(f"❌ Load failed (exit code {returncode})")
                                    with st.expander("Show error"):
                                        st.code(stderr)
                                    st.stop()
                            
                            # Update state
                            st.session_state.pipeline_state['loaded_to_graph'] = True
                            st.rerun()
                        
                        except Exception as e:
                            st.error(f"❌ Load failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
                
                # Manual Neo4j Browser link
                st.markdown("---")
                st.markdown("### 🔍 View in Neo4j Browser")
                
                browser_url = st.session_state.neo4j_uri.replace('bolt://', 'http://').replace(':7687', ':7474')
                st.markdown(f"Open [Neo4j Browser]({browser_url}) to visualize and query the graph.")
                
                st.code("""
// Example queries to try in Neo4j Browser:

// 1. Show all node types and counts
MATCH (n)
RETURN labels(n)[0] AS type, count(n) AS count
ORDER BY count DESC

// 2. Find first-line treatments for depression
MATCH (d:Drug)-[r:FIRST_LINE_FOR]->(c:Condition)
WHERE c.normalized_name CONTAINS "depressive"
RETURN d.name, r.confidence, r.evidence
ORDER BY r.confidence DESC
LIMIT 1000

// 3. Show drug with most connections
MATCH (d:Drug)-[r]->()
RETURN d.name, count(r) AS connections
ORDER BY connections DESC
LIMIT 1000
                """, language="cypher")
                
    # Pipeline Summary
    st.markdown("---")
    all_stages_complete = all(st.session_state.pipeline_state[k] for k in ['parsed', 'extracted', 'validated', 'quality_checked', 'normalized', 'loaded_to_graph'])
    
    if all_stages_complete:
        st.success("🎉 **Pipeline 100% Complete!**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            **✅ Completed Stages:**
            - ✓ Parsed document structure
            - ✓ Extracted clinical facts
            - ✓ Validated fact quality
            - ✓ Assessed precision
            - ✓ Normalized to ontologies
            - ✓ Loaded to Neo4j graph
            """)
        
        with col2:
            st.markdown(f"""
            **📁 Output Files:**
            - `data/interim/{paper_id}_parsed.json`
            - `data/processed/extracted/{paper_id}_extracted.json`
            - `data/processed/validated/{paper_id}_validated.json`
            - `data/eval/{paper_id}_quality_report.json`
            - `data/processed/normalized/{paper_id}_normalized.json`
            - **Neo4j Database:** [{st.session_state.neo4j_uri}]({st.session_state.neo4j_uri.replace('bolt://', 'http://').replace(':7687', ':7474')})
            """)
        
        # Action buttons
        st.markdown("### 🎯 Next Actions")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔍 Open Neo4j Browser"):
                browser_url = st.session_state.neo4j_uri.replace('bolt://', 'http://').replace(':7687', ':7474')
                st.markdown(f"[Open Neo4j Browser]({browser_url})")
        
        with col2:
            if st.button("📊 View Quality Report"):
                quality_path = Path("data/eval") / f"{paper_id}_quality_report.json"
                if quality_path.exists():
                    data = load_json_safe(quality_path)
                    st.json(data)
        
        with col3:
            if st.button("📄 Add Another Paper"):
                reset_pipeline()
                st.session_state.current_paper = None
                st.rerun()
    
    elif all(st.session_state.pipeline_state[k] for k in ['parsed', 'extracted', 'validated', 'quality_checked', 'normalized']):
        st.info("💡 **Almost Done!** Load to Neo4j to complete the pipeline")
          
    # Debug panel
    with st.expander("🔧 Debug Info"):
        st.json({
            "paper_id": paper_id,
            "execution_mode": st.session_state.execution_mode,
            "pipeline_state": st.session_state.pipeline_state,
            "data_keys": list(st.session_state.paper_data.keys()),
            "quality_threshold": quality_threshold,
            "min_fuzzy_score": min_fuzzy_score,
            "default_quality_methods": st.session_state.default_quality_methods
        })

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
Brightside Health AI Studio | Clinical Knowledge Graph Pipeline<br/>
Execution Mode: {mode} | Human-in-the-Loop Control
</div>
""".format(mode="Direct Import" if st.session_state.execution_mode == "direct" else "Subprocess Isolation"), unsafe_allow_html=True)