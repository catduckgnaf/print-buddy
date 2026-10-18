#!/usr/bin/env python3
"""
Download models/files (STL, 3MF, etc.) directly from Printables.com via GraphQL API.
No account or browser login required.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

GRAPHQL_URL = "https://api.printables.com/graphql/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.printables.com",
    "Referer": "https://www.printables.com/"
}

def extract_model_id(input_str: str) -> str:
    input_str = input_str.strip()
    match = re.search(r'/model/(\d+)', input_str)
    if match:
        return match.group(1)
    if input_str.isdigit():
        return input_str
    raise ValueError(f"Could not parse Printables model ID from: {input_str}")

def fetch_model_info(model_id: str):
    payload = {
        "variables": {"id": str(model_id)},
        "query": """query ModelFiles($id: ID!) {
          model: print(id: $id) {
            id
            name
            stls { id name fileSize }
            gcodes { id name fileSize }
            otherFiles { id name fileSize }
          }
        }"""
    }
    req = urllib.request.Request(GRAPHQL_URL, data=json.dumps(payload).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    model = data.get("data", {}).get("model")
    if not model:
        raise ValueError(f"Model ID {model_id} not found on Printables")
    return model

def get_download_url(file_id: str, model_id: str, file_type: str = "stl") -> str:
    payload = {
        "operationName": "GetDownloadLink",
        "variables": {
            "id": str(file_id),
            "printId": str(model_id),
            "source": "model_detail",
            "fileType": file_type
        },
        "query": """mutation GetDownloadLink($id: ID!, $printId: ID!, $source: DownloadSourceEnum!, $fileType: DownloadFileTypeEnum!) {
          getDownloadLink(id: $id, printId: $printId, source: $source, fileType: $fileType) {
            ok
            output { link }
            errors { field messages }
          }
        }"""
    }
    req = urllib.request.Request(GRAPHQL_URL, data=json.dumps(payload).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    dl = data.get("data", {}).get("getDownloadLink", {})
    if dl.get("ok") and dl.get("output", {}).get("link"):
        return dl["output"]["link"]
    errors = dl.get("errors") or []
    raise RuntimeError(f"Failed to get download URL for file {file_id}: {errors}")

def download_file(url: str, output_path: str):
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with urllib.request.urlopen(req, timeout=60) as resp, open(output_path, "wb") as f:
        chunk_size = 1024 * 1024
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)

def main():
    parser = argparse.ArgumentParser(description="Download 3D model files from Printables")
    parser.add_argument("url_or_id", help="Printables model URL or model ID")
    parser.add_argument("-o", "--output-dir", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--list-only", action="store_true", help="List files without downloading")
    args = parser.parse_args()

    model_id = extract_model_id(args.url_or_id)
    model = fetch_model_info(model_id)
    print(f"Model [{model['id']}]: {model['name']}")

    files = model.get("stls", []) + model.get("otherFiles", [])
    if not files:
        print("No model files found.")
        return

    print(f"Found {len(files)} file(s):")
    for f in files:
        size_mb = f['fileSize'] / (1024 * 1024)
        print(f"  - {f['name']} ({size_mb:.2f} MB, ID: {f['id']})")

    if args.list_only:
        return

    for f in files:
        f_id = f["id"]
        f_name = f["name"]
        dest = os.path.join(args.output_dir, f_name)
        print(f"\nFetching link for {f_name}...")
        dl_url = get_download_url(f_id, model_id)
        print(f"Downloading -> {dest}...")
        t0 = time.time()
        download_file(dl_url, dest)
        t1 = time.time()
        print(f"Downloaded {f_name} ({os.path.getsize(dest)} bytes in {t1 - t0:.2f}s)")

if __name__ == "__main__":
    main()
