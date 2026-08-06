#!/usr/bin/env python3
"""
analysis_engine.py — Independent Python + ChromaDB analysis engine.

Loads corpus.jsonl (produced by build_corpus.py), embeds each document with
Sentence-BERT, stores vectors in a persistent ChromaDB collection, and exposes
a /search endpoint that Open WebUI's Safety Analyst tool calls.

This is deliberately separate from Open WebUI's own built-in RAG — it's where
your project's actual retrieval/clustering logic lives, so you can iterate on
embedding model choice, chunking, and theme clustering independently of the
chat UI.

Usage:
    pip install fastapi uvicorn chromadb sentence-transformers
    python analysis_engine.py --corpus corpus.jsonl

Then it listens on http://localhost:8010 with:
    POST /search   {"query": "...", "top_k": 5}
    GET  /health
"""

import argparse
import json
import os

import chromadb
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "nuclear_safety_records"
CHROMA_PATH = "./chroma_store"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # swap for a domain-tuned SBERT model later

app = FastAPI(title="Nuclear Safety Analysis Engine")
model = SentenceTransformer(EMBEDDING_MODEL)
client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(COLLECTION_NAME)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    accession_number: str
    title: str | None = None
    document_type: list | None = None
    document_date: str | None = None
    score: float
    snippet: str


def ingest(corpus_path: str, batch_size: int = 64):
    """One-time (or incremental) ingestion of corpus.jsonl into ChromaDB."""
    if collection.count() > 0:
        print(f"Collection already has {collection.count()} documents. "
              f"Delete {CHROMA_PATH} first if you want to re-ingest from scratch.")
        return

    ids, texts, metadatas = [], [], []

    def flush():
        if not ids:
            return
        embeddings = model.encode(texts, show_progress_bar=False).tolist()
        collection.add(ids=list(ids), embeddings=embeddings, metadatas=list(metadatas), documents=list(texts))
        ids.clear(); texts.clear(); metadatas.clear()

    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            acc = rec.get("accession_number")
            content = rec.get("content") or ""
            if not acc or not content:
                continue
            ids.append(acc)
            texts.append(content[:5000])  # cap per-doc text for embedding speed; chunk properly later
            metadatas.append({
                "title": rec.get("title") or "",
                "document_type": ", ".join(rec.get("document_type") or []),
                "document_date": rec.get("document_date") or "",
                "docket_number": ", ".join(rec.get("docket_number") or []),
            })
            if len(ids) >= batch_size:
                flush()
    flush()
    print(f"Ingested {collection.count()} documents into '{COLLECTION_NAME}'.")


@app.get("/health")
def health():
    return {"status": "ok", "documents": collection.count()}


@app.post("/search", response_model=list[SearchResult])
def search(req: SearchRequest):
    query_embedding = model.encode([req.query]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=req.top_k)

    out = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for i in range(len(ids)):
        meta = metas[i] or {}
        out.append(SearchResult(
            accession_number=ids[i],
            title=meta.get("title"),
            document_type=[t.strip() for t in (meta.get("document_type") or "").split(",") if t.strip()],
            document_date=meta.get("document_date"),
            score=1 - dists[i] if dists[i] is not None else 0.0,  # convert distance to a similarity-ish score
            snippet=(docs[i] or "")[:400],
        ))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="corpus.jsonl")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    if os.path.exists(args.corpus):
        ingest(args.corpus)
    else:
        print(f"WARNING: {args.corpus} not found — starting with an empty collection. "
              f"Run ingestion separately once you have a corpus file.")

    uvicorn.run(app, host="0.0.0.0", port=args.port)
