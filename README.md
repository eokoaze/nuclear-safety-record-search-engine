# Nuclear Safety Record Search Engine pipeline set-up guide

This set-uup guide ties together everything into one runnable stack: pull the corpus from
ADAMS, spin up Qwen3 + Open WebUI + the independent ChromaDB engine in
Docker, and populate both the chat UI's knowledge base and your own search
engine from the same source file.

## File map

```
.
├── build_corpus.py              # Step A: pull documents from the ADAMS API
├── data/
│   └── corpus.jsonl              # <- output of build_corpus.py goes here
├── convert_corpus.py             # Step B: corpus.jsonl -> per-document .txt files
├── setup_knowledge_base.py       # Step C: uploads those .txt files into Open WebUI via API
├── docker-compose.yml            # Step D: Ollama + Open WebUI + analysis engine, networked
├── analysis-engine/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── analysis_engine.py        # your independent SBERT + ChromaDB search engine
├── safety_analyst_tool.py        # paste into Open WebUI as a Workspace Tool
└── run_pipeline.sh               # runs Steps B-D in order
```

## One-time setup

1. Build your corpus :
   ```bash
   pip install requests
   export ADAMS_API_KEY="your-subscription-key"
   python build_corpus.py --doc-types "Inspection Report" "Part 21 Correspondence" \
       --start-year 2015 --end-year 2025 --out data/corpus.jsonl
   ```

2. Make sure Docker Desktop is running.

3. From this folder, run:
   ```bash
   chmod +x run_pipeline.sh
   ./run_pipeline.sh
   ```

   This will:
   - Start Ollama, Open WebUI, and the analysis engine as containers
   - Pull `qwen3:14b` and `nomic-embed-text` into Ollama
   - Wait for all three services to report healthy
   - Convert `data/corpus.jsonl` into `docs/*.txt` (the engine ingests the
     JSONL directly on its own startup — no manual step needed for that side)

4. The script will then print two short manual steps and pause:

   **a) Populate the Open WebUI knowledge base.** Grab an API key from
   Open WebUI (Settings > Account > API Keys), then:
   ```bash
   python3 setup_knowledge_base.py --docs-dir ./docs \
       --name "NRC Safety Records" --api-key <your-key>
   ```

   **b) Create the Safety Analyst model and wire in the Tool**, in the
   Open WebUI UI itself (Workspace > Models, Workspace > Tools) — exact
   clicks are in the printed instructions and in `Local_Stack_Setup_Guide.md`.

   These two stay manual on purpose: (a) could be automated further, but
   splitting it out means you can re-run it independently whenever you add
   new documents without restarting the whole stack; (b) — the system
   prompt and model wiring — is a judgment call about how the Safety Analyst
   should behave, not something to script away.

## After setup: your steady-state workflow

Once it's running, updating the corpus later is just:

```bash
python build_corpus.py --doc-types "Inspection Report" --start-year 2026 --end-year 2026 \
    --out data/corpus.jsonl   # appends new records
docker compose restart analysis-engine   # re-ingests corpus.jsonl (add new docs only — see note below)
python convert_corpus.py --corpus data/corpus.jsonl --out ./docs
python setup_knowledge_base.py --docs-dir ./docs --name "NRC Safety Records" --api-key <your-key>
```

**Note on re-ingestion:** `analysis_engine.py` currently skips ingestion if
the ChromaDB collection already has documents (see the check at the top of
`ingest()`), so a plain restart won't pick up new rows. For incremental
updates, either delete the `chroma_store` Docker volume to force a full
re-ingest, or extend `ingest()` to skip only IDs already in the collection
(a natural next improvement once your corpus is updated regularly).

## Sanity checks

- `curl http://localhost:11434/api/tags` — Ollama is up, lists pulled models
- `curl http://localhost:3000/health` — Open WebUI is up
- `curl http://localhost:8010/health` — analysis engine is up, reports document count
- In a chat with **Safety Analyst** selected, ask something the base model
  couldn't know (a specific incident from your corpus) and confirm it either
  cites the knowledge base or calls `search_safety_records`.
