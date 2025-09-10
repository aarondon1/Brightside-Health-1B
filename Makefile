.PHONY: help setup install test format clean run parse extract normalize build pipeline docker-up docker-down

# Default target
help:
	@echo "Brightside Health AI Studio - Available Commands:"
	@echo ""
	@echo "🚀 Getting Started:"
	@echo "  make setup          - Complete project setup (one command!)"
	@echo "  make run            - Start Streamlit app"
	@echo "  make pipeline       - Run full pipeline (parse → extract → normalize → build)"
	@echo ""
	@echo "🔧 Development:"
	@echo "  make install        - Install Python dependencies"
	@echo "  make test           - Run tests"
	@echo "  make format         - Format code with black"
	@echo "  make clean          - Clean temporary files"
	@echo ""
	@echo "📊 Pipeline Steps:"
	@echo "  make parse          - Parse PDFs with Docling"
	@echo "  make extract        - Extract entities with GPT-4o"
	@echo "  make normalize      - Normalize to clinical ontologies"
	@echo "  make build          - Build knowledge graph"
	@echo ""
	@echo "🐳 Docker (Optional):"
	@echo "  make docker-up      - Start with Docker"
	@echo "  make docker-down    - Stop Docker containers"

# 🚀 Main Setup Command
setup: install setup-data setup-env
	@echo "✅ Complete setup finished! Run 'make run' to start the app."

install:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -e .
	@echo "✅ Dependencies installed!"

setup-data:
	@echo "📁 Creating data directories..."
	mkdir -p data/raw/papers data/processed/{parsed,extracted,normalized} data/ontologies outputs/{graphs,reports,evaluations}
	@echo "✅ Data directories created!"

setup-env:
	@echo "⚙️ Setting up environment..."
	cp .env.example .env
	@echo "✅ Environment file created! Edit .env with your API keys."

# 🔧 Development Commands
test:
	pytest tests/ -v
	@echo "✅ Tests completed!"

format:
	black src/ tests/ scripts/ --line-length=88
	@echo "✅ Code formatted!"

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .pytest_cache/ dist/ build/
	@echo "✅ Cleaned up!"

# 📊 Pipeline Commands
parse:
	@echo "📄 Parsing papers..."
	python scripts/run_pipeline.py --step parse
	@echo "✅ Parsing complete!"

extract:
	@echo "🧠 Extracting entities..."
	python scripts/run_pipeline.py --step extract
	@echo "✅ Extraction complete!"

normalize:
	@echo "🏥 Normalizing to ontologies..."
	python scripts/run_pipeline.py --step normalize
	@echo "✅ Normalization complete!"

build:
	@echo "📊 Building knowledge graph..."
	python scripts/run_pipeline.py --step build
	@echo "✅ Graph built!"

pipeline: parse extract normalize build
	@echo "🎉 Full pipeline completed successfully!"

# 🚀 Run Application
run:
	@echo "🚀 Starting Streamlit app at http://localhost:8501"
	python3 -m streamlit run src/visualization/streamlit_app.py

# 🐳 Docker Commands (Optional)
docker-up:
	@echo "🐳 Starting with Docker..."
	docker-compose up --build
	@echo "🚀 App running at http://localhost:8501"

docker-down:
	docker-compose down
	@echo "🛑 Docker containers stopped"