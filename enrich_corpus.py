#!/usr/bin/env python3
"""
enrich_corpus.py -- fill in missing full-text 'content' for ADAMS records.

The ADAMS search endpoint returns mostly metadata. This tool reads your
corpus.jsonl and, for any record whose 'content' is empty or too short,
calls the ADAMS "Get Document" endpoint

    GET https://adams-api.nrc.gov/aps/api/search/{accessionNumber}

which returns the document's indexed plain-text content, then writes an
enriched copy. Safe to re-run; it only re-fetches thin records.

Requirements:  pip install requests
Set your key first:
    Git Bash / macOS / Linux:  export ADAMS_API_KEY="your-subscription-key"
    PowerShell:                $env:ADAMS_API_KEY="your-subscription-key"

Usage (overwrite in place once you're happy):
    python enrich_corpus.py --in data/corpus.jsonl --out data/corpus.jsonl
Or write to a new file first to inspect it:
    python enrich_corpus.py --in data/corpus.jsonl --out data/corpus.enriched.jsonl
"""
import argparse
import base64
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

GET_DOC = "https://adams-api.nrc.gov/aps/api/search/{acc}"


def get_key():
    key = os.environ.get("ADAMS_API_KEY")
    if not key:
        sys.exit("ERROR: set ADAMS_API_KEY first "
                 '(Git Bash: export ADAMS_API_KEY="..."   PowerShell: $env:ADAMS_API_KEY="...")')
    return key


def first(rec, *names):
    """Return the first present, non-empty value among the given field names."""
    for n in names:
        v = rec.get(n)
        if v:
            return v
    return None


def maybe_b64_decode(text):
    """Content may be base64 OR plain text. Decode only when it clearly looks
    like a base64 blob (no sentence-like spacing), otherwise return as-is."""
    if not isinstance(text, str) or not text.strip():
        return ""
    s = text.strip()
    compact = re.sub(r"\s+", "", s)
    space_ratio = (len(s) - len(compact)) / max(len(s), 1)
    looks_b64 = (len(compact) >= 24 and space_ratio < 0.02
                 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact) is not None)
    if looks_b64:
        try:
            decoded = base64.b64decode(compact, validate=False).decode("utf-8", errors="ignore")
            printable = sum(c.isprintable() or c in "\n\r\t" for c in decoded)
            if decoded and printable / max(len(decoded), 1) > 0.85:
                return decoded
        except Exception:
            pass
    return text


def fetch_content(acc, key, session):
    url = GET_DOC.format(acc=acc)
    headers = {"Ocp-Apim-Subscription-Key": key, "Accept": "application/json"}
    for attempt in range(4):
        try:
            r = session.get(url, headers=headers, timeout=60)
            if r.status_code == 200:
                doc = (r.json() or {}).get("document", {}) or {}
                return maybe_b64_decode(doc.get("content") or "")
            if r.status_code in (429, 500, 502, 503):   # transient -> back off
                time.sleep(2 ** attempt)
                continue
            return ""   # 404 / not retrievable
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return ""


def main():
    ap = argparse.ArgumentParser(description="Enrich ADAMS corpus.jsonl with full document text.")
    ap.add_argument("--in", dest="inp", default="data/corpus.jsonl")
    ap.add_argument("--out", dest="out", default="data/corpus.enriched.jsonl")
    ap.add_argument("--min-chars", type=int, default=200,
                    help="records with content shorter than this are re-fetched (default 200)")
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="seconds between API calls, to be polite (default 0.3)")
    args = ap.parse_args()

    key = get_key()
    session = requests.Session()

    with open(args.inp, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    filled = already = thin = noacc = 0
    for i, rec in enumerate(rows, 1):
        content = rec.get("content") or ""
        if len(content) >= args.min_chars:
            already += 1
        else:
            acc = first(rec, "accession_number", "AccessionNumber", "accessionNumber")
            if not acc:
                noacc += 1
            else:
                text = fetch_content(acc, key, session)
                if len(text) > len(content):
                    rec["content"] = text
                if len(text) >= args.min_chars:
                    filled += 1
                else:
                    thin += 1
                time.sleep(args.sleep)
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}  (filled {filled}, still thin {thin})")

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nDone. {len(rows)} records -> {args.out}")
    print(f"  filled from Get Document : {filled}")
    print(f"  already had full content : {already}")
    print(f"  still thin after fetch   : {thin}")
    if noacc:
        print(f"  records with no accession number: {noacc}")
    if thin:
        print("  Note: 'thin' records simply have little indexed text in ADAMS. "
              "If you need those, download the PDF from each record's 'Url' and extract text.")


if __name__ == "__main__":
    main()