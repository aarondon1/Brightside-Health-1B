.PHONY: help setup install setup-data setup-env ui add_paper test fmt lint resetdb docker-up docker-down

help:
	@echo "Brightside Health KG — Commands"
	@echo "  make setup        # install deps, create .env, init data dirs"
	@echo "  make ui           # run Streamlit app"
	@echo "  make add_paper ARGS=\"--pdf data/raw_papers/file.pdf\""
	@echo "  make test | fmt | lint | resetdb"
	@echo "  make docker-up | docker-down   # (optional)"

# --- Setup ---
setup: install setup-data setup-env
	@echo "✅ Setup complete. Next: make add_paper ARGS=\"--pdf data/raw_papers/sample.pdf\" && make ui"

# Use uv (fast) or Switch to pip if you prefer.
install:
	uv sync --all-extras
	@echo "✅ Dependencies installed!"

setup-data:
	@echo "📁 Creating data directories..."
	mkdir -p data/raw_papers data/interim data/processed data/kg_db
	@echo "✅ Data directories ready."

setup-env:
	@echo "⚙️ Preparing .env..."
	cp -n .env.example .env || true
	@echo "✅ Edit .env to add keys if needed."

# --- Dev helpers ---
ui:
	@echo "🚀 Streamlit at http://localhost:8501"
	uv run streamlit run src/app/streamlit_app.py

# Run the end-to-end ingest for a new paper (parse→extract→normalize→upsert)
add_paper:
	uv run python scripts/add_paper.py $(ARGS)

test:
	uv run pytest -q

fmt:
	uv run ruff check --fix .
	uv run black .

lint:
	uv run ruff check .
	uv run black --check .

resetdb:
	rm -rf data/kg_db && mkdir -p data/kg_db
	@echo "🧹 Reset Kùzu DB."

# --- Docker (optional) ---
docker-up:
	docker compose up --build

docker-down:
	docker compose down
