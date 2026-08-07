#!/usr/bin/env python3
"""
convert_corpus.py — Turn corpus.jsonl (from build_corpus.py) into one .txt file
per document, ready for Open WebUI's knowledge base uploader (Step 7) or for
setup_knowledge_base.py to upload automatically via the API.

Usage:
    python convert_corpus.py --corpus corpus.jsonl --out ./docs
"""

import argparse
import json
import os
import re


def safe_filename(accession_number: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", accession_number) + ".txt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--out", default="./docs")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    count = 0

    with open(args.corpus, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            acc = rec.get("accession_number")
            content = rec.get("content") or ""
            if not acc or not content:
                continue

            header = (
                f"Accession Number: {acc}\n"
                f"Title: {rec.get('title', '')}\n"
                f"Document Type: {', '.join(rec.get('document_type') or [])}\n"
                f"Document Date: {rec.get('document_date', '')}\n"
                f"Docket Number: {', '.join(rec.get('docket_number') or [])}\n"
                f"Author: {rec.get('author_name', '')} ({rec.get('author_affiliation', '')})\n"
                f"URL: {rec.get('url', '')}\n"
                f"{'-' * 40}\n\n"
            )

            path = os.path.join(args.out, safe_filename(acc))
            with open(path, "w", encoding="utf-8") as out_f:
                out_f.write(header + content)
            count += 1

    print(f"Wrote {count} document files to {args.out}/")


if __name__ == "__main__":
    main()
