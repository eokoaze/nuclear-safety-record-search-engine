#!/usr/bin/env python3
"""
setup_knowledge_base.py — Create an Open WebUI knowledge base and upload a
directory of documents into it via the REST API (automates Step 7 so you're
not clicking "upload" hundreds of times).

Get your API key from Open WebUI: Settings > Account > API Keys.

Usage:
    python setup_knowledge_base.py \
        --base-url http://localhost:3000 \
        --api-key sk-... \
        --docs-dir ./docs \
        --name "NRC Inspection Reports" \
        --description "ADAMS-derived inspection report corpus"
"""

import argparse
import os
import sys
import time

import requests


def create_knowledge(base_url, headers, name, description):
    resp = requests.post(
        f"{base_url}/api/v1/knowledge/create",
        headers=headers,
        json={"name": name, "description": description, "data": {}, "access_control": {}},
    )
    resp.raise_for_status()
    kb = resp.json()
    print(f"Created knowledge base '{name}' -> id={kb['id']}")
    return kb["id"]


def upload_and_link(base_url, headers, knowledge_id, file_path):
    """Single-call path: upload with knowledge_id in metadata so the server
    auto-links it server-side (recommended — robust to client disconnects)."""
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        data = {"metadata": f'{{"knowledge_id": "{knowledge_id}"}}'}
        resp = requests.post(
            f"{base_url}/api/v1/files/",
            headers={"Authorization": headers["Authorization"], "Accept": "application/json"},
            files=files,
            data=data,
        )
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_processing(base_url, headers, file_id, timeout=120, poll_interval=2):
    elapsed = 0
    while elapsed < timeout:
        resp = requests.get(f"{base_url}/api/v1/files/{file_id}/process/status", headers=headers)
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status in ("completed", "done", "success"):
                return True
            if status in ("failed", "error"):
                print(f"  [warn] file {file_id} processing failed")
                return False
        time.sleep(poll_interval)
        elapsed += poll_interval
    print(f"  [warn] file {file_id} still processing after {timeout}s — continuing anyway")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    ap.add_argument("--api-key", default=os.environ.get("OPEN_WEBUI_API_KEY"))
    ap.add_argument("--docs-dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--wait-for-processing", action="store_true",
                     help="Poll each file's processing status before moving to the next (slower, safer)")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("ERROR: pass --api-key or set OPEN_WEBUI_API_KEY (Settings > Account > API Keys in Open WebUI).")

    headers = {"Authorization": f"Bearer {args.api_key}"}

    knowledge_id = create_knowledge(args.base_url, headers, args.name, args.description)

    files = [f for f in sorted(os.listdir(args.docs_dir)) if f.endswith(".txt")]
    print(f"Uploading {len(files)} files into knowledge base '{args.name}'...")

    for i, fname in enumerate(files, 1):
        path = os.path.join(args.docs_dir, fname)
        try:
            file_id = upload_and_link(args.base_url, headers, knowledge_id, path)
            if args.wait_for_processing:
                wait_for_processing(args.base_url, headers, file_id)
            if i % 25 == 0 or i == len(files):
                print(f"  {i}/{len(files)} uploaded")
        except requests.RequestException as e:
            print(f"  [error] failed to upload {fname}: {e}")

    print(f"\nDone. Knowledge base '{args.name}' (id={knowledge_id}) is populated.")
    print("Note: extraction/embedding continues in the background — give it a few minutes "
          "before relying on retrieval if you skipped --wait-for-processing.")


if __name__ == "__main__":
    main()
