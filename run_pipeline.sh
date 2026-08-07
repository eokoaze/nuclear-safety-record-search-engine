#!/usr/bin/env bash
# run_pipeline.sh — End-to-end setup: brings up Ollama + Open WebUI + the
# analysis engine, pulls the models, converts your corpus, and populates
# the Open WebUI knowledge base. Run from the folder containing
# docker-compose.yml, analysis-engine/, convert_corpus.py, and
# setup_knowledge_base.py.
#
# Prerequisites:
#   - Docker Desktop running
#   - corpus.jsonl already built (see build_corpus.py) and placed at ./data/corpus.jsonl
#
# Usage:
#   chmod +x run_pipeline.sh
#   ./run_pipeline.sh

set -euo pipefail

CORPUS_PATH="./data/corpus.jsonl"
DOCS_DIR="./docs"
KB_NAME="NRC Safety Records"

if [ ! -f "$CORPUS_PATH" ]; then
  echo "ERROR: $CORPUS_PATH not found. Run build_corpus.py first and place the output there."
  exit 1
fi

echo "==> Starting Docker stack (Ollama, Open WebUI, analysis engine)..."
docker compose up -d --build

echo "==> Waiting for Ollama to be ready..."
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
  sleep 2
done
echo "    Ollama is up."

echo "==> Pulling models (this can take a while the first time)..."
docker compose exec -T ollama ollama pull qwen3:14b
docker compose exec -T ollama ollama pull nomic-embed-text

echo "==> Waiting for Open WebUI to be ready..."
until curl -sf http://localhost:3000/health >/dev/null 2>&1; do
  sleep 2
done
echo "    Open WebUI is up at http://localhost:3000"

echo "==> Waiting for analysis engine to be ready..."
until curl -sf http://localhost:8010/health >/dev/null 2>&1; do
  sleep 2
done
echo "    Analysis engine is up at http://localhost:8010 (it ingests $CORPUS_PATH on startup)"

echo "==> Converting corpus into per-document files for the knowledge base..."
python3 convert_corpus.py --corpus "$CORPUS_PATH" --out "$DOCS_DIR"

echo ""
echo "============================================================"
echo " Automated setup complete. Two manual steps remain:"
echo ""
echo " 1) Get an Open WebUI API key:"
echo "    open http://localhost:3000 -> log in (first login = admin)"
echo "    -> Settings > Account > API Keys -> create one"
echo ""
echo "    Then run:"
echo "    python3 setup_knowledge_base.py --docs-dir $DOCS_DIR \\"
echo "        --name \"$KB_NAME\" --api-key <your-key>"
echo ""
echo " 2) In the Open WebUI UI:"
echo "    - Workspace > Models > + Create a Model"
echo "        base model: qwen3:14b, name: Safety Analyst"
echo "        attach the '$KB_NAME' knowledge base"
echo "    - Workspace > Tools > + Create a Tool"
echo "        paste in safety_analyst_tool.py"
echo "        set the 'engine_url' valve to: http://analysis-engine:8010"
echo "        (use the Docker service name, not host.docker.internal,"
echo "         since both containers now share the compose network)"
echo "    - Back in Workspace > Models > Safety Analyst > edit:"
echo "        enable the tool, set Function Calling = Native, save"
echo "============================================================"
