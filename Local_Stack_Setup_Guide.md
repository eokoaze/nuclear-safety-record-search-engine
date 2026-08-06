# Local Stack Setup Guide: Qwen3 + Open WebUI + ChromaDB "Safety Analyst"

This follows your supervisor's ten steps in order. Where a step depends on decisions
made in an earlier one (e.g. which embedding model, which port), it's called out.

**Before you start — hardware check:** Qwen3 14B at 4-bit quantization needs roughly
9–10GB of VRAM (or will fall back to slower CPU+RAM inference needing ~16GB+ system
RAM). If your machine doesn't have a GPU with that much VRAM, mention it to your
supervisor now — you may want `qwen3:8b` instead, which is a drop-in swap everywhere
below.

---

## 1. Download Qwen3 14B

You'll run Qwen3 through **Ollama**, which handles downloading, quantization, and
serving. Install Ollama first if you haven't:

- **macOS**: `brew install ollama` or download from ollama.com
- **Windows**: download the installer from ollama.com
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`

Then pull the model:

```bash
ollama pull qwen3:14b
```

Verify it runs:

```bash
ollama run qwen3:14b
```

Type a test prompt, confirm you get a response, then `/bye` to exit. Qwen3 supports a
toggleable "thinking mode" — you can append `/think` or `/no_think` to a prompt later if
you want to compare reasoning-heavy vs. fast responses for your evaluation section.

## 2. Download a dedicated embedding model

Don't use Qwen3 itself for embeddings — use a model built for it. `nomic-embed-text` is
the standard pick for local Ollama setups (small, fast, good general-purpose retrieval
quality):

```bash
ollama pull nomic-embed-text
```

This is what turns your ADAMS documents (and user queries) into vectors for semantic
search — separate from Qwen3, which only handles generation.

## 3. Install Docker Desktop

Open WebUI runs as a container, so you need Docker first.

- **Windows/macOS**: download Docker Desktop from docker.com and run the installer
  (Windows requires WSL2 — the installer will prompt you if it's missing).
- **Linux**: install Docker Engine via your package manager, or Docker Desktop for
  Linux if you prefer the GUI.

Confirm it's working:

```bash
docker --version
docker run hello-world
```

## 4. Install Open WebUI

With Ollama already running on your host machine, install Open WebUI as a container
that talks to it:

```bash
docker run -d -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

- `-p 3000:8080` — Open WebUI will be reachable at `http://localhost:3000`
- `-v open-webui:/app/backend/data` — persists your data (chats, knowledge bases,
  model configs) across container restarts; don't skip this
- `--add-host=host.docker.internal:host-gateway` — lets the container reach Ollama
  running on your host

Open `http://localhost:3000`, create your admin account (first signup becomes admin).

## 5. Connect Open WebUI to Ollama

Usually auto-detected, but to confirm or set manually:

1. In Open WebUI, go to **Admin Settings > Connections > Ollama** (wrench/manage icon).
2. If Ollama is running on your host machine and Open WebUI is in Docker, the URL should be:
   ```
   http://host.docker.internal:11434
   ```
3. Save, and you should see `qwen3:14b` and `nomic-embed-text` appear in the model
   list — confirming the connection works.

## 6. Configure document search in Open WebUI

This controls how Open WebUI's built-in RAG chunks, embeds, and retrieves from
anything you upload as Knowledge.

1. Go to **Admin Settings > Documents**.
2. Set **Embedding Model Engine** to Ollama, and the model to `nomic-embed-text`.
3. Set chunk size and chunk overlap (start with defaults — ~1000 tokens / 100 overlap
   is a reasonable baseline for report-style documents; tune later based on retrieval
   quality).
4. Consider enabling **Hybrid Search** — it combines keyword (BM25-style) matching with
   vector similarity, which tends to help on documents with exact identifiers like
   accession numbers, docket numbers, and report IDs — exactly what your ADAMS corpus
   has plenty of.
5. Save.

## 7. Build knowledge bases in Open WebUI

1. Go to **Workspace > Knowledge**.
2. Click **+ Create a Knowledge Base** (or **+ New Knowledge**, depending on version).
3. Name it something specific, e.g. `NRC Inspection Reports` — if you're organizing by
   `DocumentType` (as recommended in your corpus-building guide), create one knowledge
   base per major type rather than dumping everything into one bucket. That keeps
   retrieval scoped and makes it easier to reference `#knowledge-base-name` in chat
   later.
4. Upload content: **Upload File** for individual documents, or **Upload Directory**
   if you've exported your `corpus.jsonl` records out to individual `.txt`/`.pdf`
   files first (Open WebUI's document uploader expects file-per-document, not a single
   JSONL blob — see the note at the end of this guide on converting your corpus).
5. Wait for processing to finish (it's chunking + embedding each file — large batches
   take a while; don't navigate away mid-upload).

## 8. Create the Safety Analyst model

This wraps Qwen3 14B with a system prompt and your knowledge base into a single
selectable "model" in the chat dropdown.

1. Go to **Workspace > Models > + Create a Model**.
2. **Base model**: `qwen3:14b`
3. **Name**: `Safety Analyst`
4. **System prompt** — this is where you encode the analyst persona, e.g.:
   > You are a nuclear safety records analyst. Answer questions about NRC incident,
   > inspection, and licensee event reports using only the retrieved document context
   > provided to you. Cite accession numbers when referencing specific reports. If the
   > retrieved context doesn't contain a clear answer, say so explicitly rather than
   > guessing.
5. **Knowledge**: attach the knowledge base(s) you built in Step 7.
6. Check your context size setting — larger context lets you feed in more retrieved
   chunks per query, but uses more VRAM/RAM. Watch `ollama ps` in a terminal while
   testing to see actual memory use and tune accordingly.
7. Save. `Safety Analyst` now appears in the model dropdown for new chats.

Test it: start a new chat, select **Safety Analyst**, ask a question that should be
answerable from your uploaded documents, and confirm it retrieves and cites correctly
before moving on.

## 9. Add the independent Python and ChromaDB engine

This is the part that's actually *yours* — distinct from Open WebUI's built-in RAG
(Step 6–7). Where Open WebUI's document search does generic chunk-and-embed retrieval,
your independent engine is where your project's real ML work lives: the TF-IDF
baseline, SBERT semantic embeddings, and clustering logic from your research design,
running against ChromaDB as the vector store, as its own standalone service.

Build it as a small FastAPI app that:

1. Loads your `corpus.jsonl` (from the ADAMS corpus-building step).
2. Embeds each document with Sentence-BERT and stores vectors in a ChromaDB collection.
3. Exposes a `/search` endpoint that takes a natural-language query, embeds it, and
   returns the top-matching documents plus (optionally) their cluster/theme label.

A starter implementation (`analysis_engine.py`) is included alongside this guide.
Run it separately from Open WebUI:

```bash
pip install fastapi uvicorn chromadb sentence-transformers
python analysis_engine.py
```

By default it listens on `http://localhost:8010`. Keep this running in its own
terminal/process — it's intentionally decoupled from the Open WebUI container.

## 10. Connect the analysis engine to Open WebUI

The clean way to wire a custom backend like this into Open WebUI is a **Workspace
Tool** — a Python function that Qwen3 can call (via native function calling) whenever
it decides it needs to search your engine, rather than relying on static
retrieve-then-generate.

1. Go to **Workspace > Tools > + Create a Tool**.
2. Paste in a tool script that calls your `analysis_engine.py` `/search` endpoint (a
   starter version, `safety_analyst_tool.py`, is included alongside this guide —
   copy its contents into the tool editor).
3. Name it something like `search_safety_records`, save.
4. Go back to **Workspace > Models > Safety Analyst > edit**, scroll to **Tools**,
   enable `search_safety_records`, save.
5. Confirm **Function Calling** is set to **Native** for this model (Admin Settings >
   Models > Safety Analyst > Advanced Params, or per-chat in Chat Controls) — Native
   mode is what lets Qwen3 actually decide to invoke your tool mid-conversation rather
   than ignoring it.

Test it: ask the Safety Analyst something that requires your clustering/theme logic
specifically (not just document lookup) — e.g. "what failure themes show up across
2023 inspection reports for pressurized water reactors?" — and confirm in the response
(or the tool-call trace, if your Open WebUI version shows it) that it actually queried
your engine rather than answering from the built-in knowledge base alone.

---

## Note: getting `corpus.jsonl` into a usable shape for both systems

Your `build_corpus.py` script writes one JSON object per line. Both Step 7 (Open
WebUI's uploader) and Step 9 (your own ChromaDB ingestion) want that data in different
shapes — one as individual files, one as embedded vectors directly. Rather than
maintaining two conversions by hand, write one small script that reads `corpus.jsonl`
once and produces both: a folder of per-document `.txt` files (title + metadata header
+ content) for Step 7, and feeds the same records into `analysis_engine.py`'s ingestion
routine for Step 9. That keeps both systems built from the same source of truth instead
of drifting apart as your corpus grows.
