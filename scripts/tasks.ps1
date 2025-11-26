<#
Usage examples (run from repo root):
  ./scripts/tasks.ps1 -Task setup
  ./scripts/tasks.ps1 -Task ui
  ./scripts/tasks.ps1 -Task add_paper -Args "--pdf data/raw_papers/sample.pdf"
  ./scripts/tasks.ps1 -Task parse     -Args "--source data/raw_papers/sample.pdf"
  ./scripts/tasks.ps1 -Task extract   -Args "--input data/interim/sample_parsed.json"
  ./scripts/tasks.ps1 -Task validate  -Args "--input data/processed/extracted/sample_extracted.json --show-details"
  ./scripts/tasks.ps1 -Task quality   -Args "--input data/processed/validated/sample_validated.json --methods heuristic"
  ./scripts/tasks.ps1 -Task normalize -Args "--input data/processed/validated/sample_validated.json"
  ./scripts/tasks.ps1 -Task load_neo4j -Args "--input data/processed/normalized/sample_normalized.json --clear"
#>

param(
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "setup","install","dirs","env",
    "ui","add_paper","parse","extract","validate",
    "quality","normalize","unmatched",
    "load_neo4j","neo4j_schema","neo4j_validate",
    "test","fmt","lint","clean"
  )]
  [string]$Task,

  [string]$Args = ""
)

function Require-Env {
  if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example (edit afterward)" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env" -ErrorAction SilentlyContinue
  }
}

function Run-Cmd ($cmd) {
  Write-Host ">> $cmd" -ForegroundColor Cyan
  powershell -NoLogo -NoProfile -Command $cmd
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Task) {

  "setup" {
    ./scripts/tasks.ps1 -Task install
    ./scripts/tasks.ps1 -Task dirs
    ./scripts/tasks.ps1 -Task env
    Write-Host "Setup complete." -ForegroundColor Green
  }

  "install" {
    if (Test-Path "requirements.txt") {
      Run-Cmd "pip install -r requirements.txt"
    } else {
      Write-Host "requirements.txt not found." -ForegroundColor Red
      exit 1
    }
  }

  "dirs" {
    "data/raw_papers","data/interim","data/processed/extracted","data/processed/validated",
    "data/processed/normalized","data/eval","data/reports" | ForEach-Object {
      New-Item -ItemType Directory -Force -Path $_ | Out-Null
    }
    Write-Host "Data directories ready." -ForegroundColor Green
  }

  "env" { Require-Env }

  "ui" {
    Require-Env
    Run-Cmd "streamlit run src/app/streamlit_app.py"
  }

  "add_paper" {
    Require-Env
    Run-Cmd "python scripts/add_paper.py $Args"
  }

  "parse"      { Run-Cmd "python scripts/parse_doc.py $Args" }
  "extract"    { Run-Cmd "python scripts/extract.py $Args" }
  "validate"   { Run-Cmd "python scripts/validate.py $Args" }
  "quality"    { Run-Cmd "python scripts/auto_validate_quality.py $Args" }
  "normalize"  { Run-Cmd "python scripts/normalize.py $Args" }
  "unmatched"  { Run-Cmd "python scripts/show_unmatched_normalized.py $Args" }
  "load_neo4j" { Run-Cmd "python scripts/load_neo4j.py $Args" }
  "neo4j_schema"   { Run-Cmd "python scripts/neo4j_schema.py" }
  "neo4j_validate" { Run-Cmd "python scripts/neo4j_validate.py" }

  "test" { Run-Cmd "pytest -q" }
  "fmt"  { Run-Cmd "black ."; Run-Cmd "ruff check --fix ." }
  "lint" { Run-Cmd "ruff check ."; Run-Cmd "black --check ." }

  "clean" {
    @("data/processed/extracted","data/processed/validated","data/processed/normalized","data/eval") |
      ForEach-Object { if (Test-Path $_) { Remove-Item -Recurse -Force $_ } }
    Write-Host "Clean complete." -ForegroundColor Green
  }
}
