# # MAKEFILE TEMP IMPLEMENTATION NEED TWEAKING: 



# # Brightside Health KG Makefile
# # Usage examples:
# #   make setup
# #   make add_paper ARGS="--pdf data/raw_papers/sample.pdf"
# #   make parse SOURCE=data/raw_papers/sample.pdf
# #   make extract PARSED=data/interim/sample_parsed.json
# #   make validate EXTRACTED=data/processed/extracted/sample_extracted.json
# #   make quality VALIDATED=data/processed/validated/sample_validated.json METHODS="heuristic nli"
# #   make normalize VALIDATED=data/processed/validated/sample_validated.json
# #   make load_neo4j FILE=data/processed/normalized/sample_validated_normalized.json CLEAR=1

# # -------- Variables --------
# PY              ?= python
# UV              := $(shell command -v uv 2>/dev/null)
# PKG_INSTALL     := $(if $(UV),uv sync --all-extras,pip install -r requirements.txt)
# ENV_FILE        := .env
# REQ_FILE        := requirements.txt

# RAW_DIR         := data/raw_papers
# INTERIM_DIR     := data/interim
# PARSED_DIR      := data/interim/parsed
# EXTRACTED_DIR   := data/processed/extracted
# VALIDATED_DIR   := data/processed/validated
# NORMALIZED_DIR  := data/processed/normalized
# EVAL_DIR        := data/eval
# REPORTS_DIR     := data/reports

# # -------- PHONY --------
# .PHONY: help setup install setup-env setup-dirs ui add_paper parse extract validate quality normalize unmatched load_neo4j neo4j_schema neo4j_validate test fmt lint clean reset_graph check_env

# help:
#     @echo "Brightside Health Clinical KG — Targets"
#     @echo "  setup                    Install deps + create dirs + copy .env"
#     @echo "  install                  Install Python dependencies (uv or pip)"
#     @echo "  setup-dirs               Create required data directory structure"
#     @echo "  setup-env                Copy .env.example → .env (non-destructive)"
#     @echo "  ui                       Run Streamlit UI"
#     @echo "  add_paper ARGS=...       Run end-to-end pipeline (parse→extract→validate→quality→normalize)"
#     @echo "  parse SOURCE=...         Parse PDF/URL → parsed JSON"
#     @echo "  extract PARSED=...       LLM extraction → extracted JSON"
#     @echo "  validate EXTRACTED=...   Validate facts → validated + issues JSON"
#     @echo "  quality VALIDATED=...    Quality assessment → quality report"
#     @echo "  normalize VALIDATED=...  Ontology normalization → normalized JSON"
#     @echo "  unmatched FILE=...       Show unmatched ontology terms"
#     @echo "  load_neo4j FILE=...      Load normalized facts into Neo4j (CLEAR=1 to wipe)"
#     @echo "  neo4j_schema             Inspect Neo4j schema"
#     @echo "  neo4j_validate           Run Neo4j data quality checks"
#     @echo "  test / fmt / lint        QA utilities"
#     @echo "  clean                    Remove intermediate processed artifacts"
#     @echo "  reset_graph              (Alias: CLEAR load) Remove graph data via loader"
#     @echo "  check_env                Verify required environment variables"

# setup: install setup-dirs setup-env
#     @echo "✅ Setup complete."

# install:
#     @echo "📦 Installing dependencies..."
#     @$(PKG_INSTALL)
#     @echo "✅ Dependencies installed."

# setup-dirs:
#     @echo "📁 Creating data directory tree..."
#     @mkdir -p $(RAW_DIR) $(PARSED_DIR) $(EXTRACTED_DIR) $(VALIDATED_DIR) $(NORMALIZED_DIR) $(INTERIM_DIR) $(EVAL_DIR) $(REPORTS_DIR)
#     @echo "✅ Directories ready."

# setup-env:
#     @echo "⚙️ Preparing environment file..."
#     @cp -n .env.example $(ENV_FILE) || true
#     @echo "➡️ Edit $(ENV_FILE) to set OPENAI_API_KEY and Neo4j credentials."

# check_env:
#     @if [ ! -f $(ENV_FILE) ]; then echo "❌ Missing $(ENV_FILE). Run: make setup-env"; exit 1; fi
#     @if ! grep -q OPENAI_API_KEY $(ENV_FILE); then echo "⚠️ OPENAI_API_KEY not set in $(ENV_FILE)"; fi
#     @echo "✅ Environment file present."

# ui:
#     @echo "🚀 Streamlit UI → http://localhost:8501"
#     @$(PY) -m streamlit run src/app/streamlit_app.py

# # -------- Stage Targets --------

# parse:
#     @if [ -z "$(SOURCE)" ]; then echo "❌ SOURCE required. Usage: make parse SOURCE=data/raw_papers/file.pdf"; exit 1; fi
#     @mkdir -p $(PARSED_DIR)
#     @echo "🔍 Parsing: $(SOURCE)"
#     @$(PY) scripts/parse_doc.py --source "$(SOURCE)" --out "$(PARSED_DIR)/$$(basename $(SOURCE) .pdf)_parsed.json"

# extract:
#     @if [ -z "$(PARSED)" ]; then echo "❌ PARSED required. Usage: make extract PARSED=data/interim/parsed/<id>_parsed.json"; exit 1; fi
#     @mkdir -p $(EXTRACTED_DIR)
#     @echo "🤖 Extracting facts from: $(PARSED)"
#     @$(PY) scripts/extract.py --input "$(PARSED)" --output "$(EXTRACTED_DIR)/$$(basename $(PARSED) _parsed.json)_extracted.json"

# validate:
#     @if [ -z "$(EXTRACTED)" ]; then echo "❌ EXTRACTED required. Usage: make validate EXTRACTED=data/processed/extracted/<id>_extracted.json"; exit 1; fi
#     @mkdir -p $(VALIDATED_DIR)
#     @echo "✅ Validating: $(EXTRACTED)"
#     @$(PY) scripts/validate.py --input "$(EXTRACTED)" --output "$(VALIDATED_DIR)/$$(basename $(EXTRACTED) _extracted.json)_validated.json" --issues "$(VALIDATED_DIR)/$$(basename $(EXTRACTED) _extracted.json)_issues.json" --show-details

# quality:
#     @if [ -z "$(VALIDATED)" ]; then echo "❌ VALIDATED required. Usage: make quality VALIDATED=data/processed/validated/<id>_validated.json [METHODS=\"heuristic nli\"]"; exit 1; fi
#     @mkdir -p $(EVAL_DIR)
#     @echo "📊 Quality assessing: $(VALIDATED)"
#     @$(PY) scripts/auto_validate_quality.py --input "$(VALIDATED)" --methods $(if $(METHODS),$(METHODS),heuristic) --output "$(EVAL_DIR)/$$(basename $(VALIDATED) _validated.json)_quality_report.json"

# normalize:
#     @if [ -z "$(VALIDATED)" ]; then echo "❌ VALIDATED required. Usage: make normalize VALIDATED=data/processed/validated/<id>_validated.json"; exit 1; fi
#     @mkdir -p $(NORMALIZED_DIR)
#     @echo "🧬 Normalizing: $(VALIDATED)"
#     @$(PY) scripts/normalize.py --input "$(VALIDATED)" --output "$(NORMALIZED_DIR)/$$(basename $(VALIDATED) _validated.json)_normalized.json"

# unmatched:
#     @if [ -z "$(FILE)" ]; then echo "❌ FILE required. Usage: make unmatched FILE=data/processed/normalized/<id>_normalized.json"; exit 1; fi
#     @echo "🔍 Unmatched ontology terms in: $(FILE)"
#     @$(PY) scripts/show_unmatched_normalized.py --input "$(FILE)"

# load_neo4j:
#     @if [ -z "$(FILE)" ]; then echo "❌ FILE required. Usage: make load_neo4j FILE=data/processed/normalized/<id>_normalized.json [CLEAR=1]"; exit 1; fi
#     @echo "📦 Loading into Neo4j: $(FILE)"
#     @$(PY) scripts/load_neo4j.py --input "$(FILE)" $(if $(CLEAR),--clear,)

# neo4j_schema:
#     @echo "🔧 Inspecting Neo4j schema..."
#     @$(PY) scripts/neo4j_schema.py

# neo4j_validate:
#     @echo "🩺 Validating Neo4j data..."
#     @$(PY) scripts/neo4j_validate.py

# add_paper:
#     @if [ -z "$(ARGS)" ]; then echo "❌ ARGS required. Example: make add_paper ARGS=\"--pdf data/raw_papers/sample.pdf\""; exit 1; fi
#     @echo "🔄 End-to-end ingest: $(ARGS)"
#     @$(PY) scripts/add_paper.py $(ARGS)

# # -------- QA / Dev --------

# test:
#     @echo "🧪 Running tests..."
#     @$(PY) -m pytest -q

# fmt:
#     @echo "🧹 Formatting..."
#     @$(PY) -m ruff check --fix .
#     @$(PY) -m black .

# lint:
#     @echo "🔍 Linting..."
#     @$(PY) -m ruff check .
#     @$(PY) -m black --check .

# clean:
#     @echo "🧹 Removing processed artifacts..."
#     @rm -rf $(EXTRACTED_DIR) $(VALIDATED_DIR) $(NORMALIZED_DIR) $(EVAL_DIR)
#     @echo "✅ Clean complete."

# reset_graph:
#     @echo "🗑️ Clearing graph (use Neo4j tools if needed)."
#     @echo "Run: make load_neo4j FILE=<normalized.json> CLEAR=1"

# # -------- Default --------
# default: help