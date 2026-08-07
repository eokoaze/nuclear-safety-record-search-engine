#!/usr/bin/env python3
"""
build_corpus.py — Pull a nuclear incident-report corpus from the NRC ADAMS
Public Search API, segmented and paginated to work around the 1,000-result
cap per query.

Usage:
    export ADAMS_API_KEY="your-subscription-key-here"
    python build_corpus.py --doc-types "Inspection Report" "Part 21 Correspondence" \
        --start-year 2015 --end-year 2025 --out corpus.jsonl

Output:
    - <out>            : JSON Lines file, one document per line
    - <out>.coverage.csv : one row per (doc_type, date_slice) with result counts,
                            so you can spot truncated slices and re-pull them
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import date

import requests

API_HOST = "https://adams-api.nrc.gov"
SEARCH_ENDPOINT = f"{API_HOST}/aps/api/search"
PAGE_SIZE_GUESS = 100          # ADAMS pages internally; we just keep incrementing skip
RESULT_CAP = 1000              # hard ceiling per query — must segment below this
MAX_RETRIES = 5
BACKOFF_BASE = 1.5
REQUEST_DELAY = 0.3            # seconds between calls, be polite to the service


def get_api_key():
    key = os.environ.get("ADAMS_API_KEY")
    if not key:
        sys.exit("ERROR: set the ADAMS_API_KEY environment variable first.")
    return key


def date_filter(start, end):
    return f"(DocumentDate ge '{start}') and (DocumentDate le '{end}')"


def search_page(session, headers, doc_type, start_date, end_date, skip):
    body = {
        "q": "",
        "content": True,
        "filters": [
            {"field": "DocumentType", "operator": "equals", "value": doc_type},
            {"field": "DocumentDate", "value": date_filter(start_date, end_date)},
        ],
        "anyFilters": [],
        "mainLibFilter": True,
        "legacyLibFilter": True,
        "sort": "DocumentDate",
        "sortDirection": 1,
        "skip": skip,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(SEARCH_ENDPOINT, headers=headers, json=body, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt
                print(f"    [retry] status {resp.status_code}, backing off {wait:.1f}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            print(f"    [retry] {e}, backing off {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {doc_type} {start_date}-{end_date} skip={skip}")


def pull_slice(session, headers, doc_type, start_date, end_date, writer, seen_ids):
    """Pull all results for one (doc_type, date range) slice. Returns total count found."""
    skip = 0
    total = None
    pulled = 0

    while True:
        data = search_page(session, headers, doc_type, start_date, end_date, skip)
        total = data.get("count", 0)
        results = data.get("results", [])

        if not results:
            break

        for r in results:
            doc = r.get("document", {})
            acc = doc.get("AccessionNumber")
            if not acc or acc in seen_ids:
                continue
            seen_ids.add(acc)
            record = {
                "accession_number": acc,
                "title": doc.get("DocumentTitle"),
                "document_type": doc.get("DocumentType"),
                "document_date": doc.get("DocumentDate"),
                "docket_number": doc.get("DocketNumber"),
                "author_name": doc.get("AuthorName"),
                "author_affiliation": doc.get("AuthorAffiliation"),
                "url": doc.get("Url"),
                "content": doc.get("content"),
            }
            writer.write(json.dumps(record) + "\n")
            pulled += 1

        skip += len(results)
        time.sleep(REQUEST_DELAY)

        if skip >= RESULT_CAP or skip >= total:
            break

    return total, pulled


def quarter_ranges(year):
    return [
        (f"{year}-01-01", f"{year}-03-31"),
        (f"{year}-04-01", f"{year}-06-30"),
        (f"{year}-07-01", f"{year}-09-30"),
        (f"{year}-10-01", f"{year}-12-31"),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc-types", nargs="+", required=True, help="ADAMS DocumentType values to pull")
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, default=date.today().year)
    ap.add_argument("--out", default="corpus.jsonl")
    args = ap.parse_args()

    headers = {
        "Ocp-Apim-Subscription-Key": get_api_key(),
        "Content-Type": "application/json",
    }
    session = requests.Session()
    seen_ids = set()

    coverage_path = args.out + ".coverage.csv"
    with open(args.out, "a", encoding="utf-8") as out_f, \
         open(coverage_path, "a", newline="", encoding="utf-8") as cov_f:

        cov_writer = csv.writer(cov_f)
        if os.stat(coverage_path).st_size == 0:
            cov_writer.writerow(["doc_type", "start_date", "end_date", "reported_count", "pulled_count", "truncated"])

        for doc_type in args.doc_types:
            for year in range(args.start_year, args.end_year + 1):
                start_date, end_date = f"{year}-01-01", f"{year}-12-31"
                print(f"[{doc_type}] {year} ...")
                total, pulled = pull_slice(session, headers, doc_type, start_date, end_date, out_f, seen_ids)

                if total is not None and total >= RESULT_CAP:
                    # Likely truncated at the year level — split into quarters and re-pull.
                    print(f"  -> {total} reported (>= cap), splitting {year} into quarters")
                    cov_writer.writerow([doc_type, start_date, end_date, total, pulled, True])
                    for q_start, q_end in quarter_ranges(year):
                        print(f"    [{doc_type}] {q_start}..{q_end} ...")
                        q_total, q_pulled = pull_slice(session, headers, doc_type, q_start, q_end, out_f, seen_ids)
                        cov_writer.writerow([doc_type, q_start, q_end, q_total, q_pulled, q_total is not None and q_total >= RESULT_CAP])
                        out_f.flush()
                else:
                    cov_writer.writerow([doc_type, start_date, end_date, total, pulled, False])

                out_f.flush()
                cov_f.flush()

    print(f"\nDone. Corpus written to {args.out} ({len(seen_ids)} unique documents).")
    print(f"Coverage log: {coverage_path} — check the 'truncated' column for any remaining gaps.")


if __name__ == "__main__":
    main()
