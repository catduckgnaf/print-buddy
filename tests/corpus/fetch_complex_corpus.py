"""Fetch the #458 complex corpus models into a local corpus root.

Storage decision (see tests/corpus/complex/README.md): the model files are
tens of MB each and are NOT committed to this repository. This script downloads
them, pinned by the SHA256 and byte size recorded in
tests/corpus/complex_cases.toml, into a root outside the repo (default
~/print-buddy-complex-corpus) laid out as one folder per case:

    <root>/<slug>/model.stl|model.3mf   the flow-run primary file
    <root>/<slug>/<extra files>         measured companion files, where any
    <root>/<slug>/case.toml             clicks + expectations for the harness
    <root>/<slug>/ATTRIBUTION           title, author, source, licence

Downloads use the same eligible-site paths as production intake (#462):
Printables through its GraphQL API (the getDownloadLink mutation
print_buddy.core.model_job.printables_download uses; no token), NASA through
its direct public file link. Private-tier cases are licence-flagged for local
runs only: they are skipped unless --private-root is given, and they are never
written into the public root.

Usage:
    python tests/corpus/fetch_complex_corpus.py [--root DIR] [--private-root DIR]
"""
import argparse
import hashlib
import json
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "complex_cases.toml"
NASA_STL = ("https://assets.science.nasa.gov/content/dam/science/cds/3d/"
            "resources/printable/curiosity-rover-(simplified)/Curiosity%20(200uM).stl")
PRINTABLES_GQL = "https://api.printables.com/graphql/"
LINK_MUTATION = """mutation GetDownloadLink($id: ID!, $printId: ID!, $source: DownloadSourceEnum!,
$fileType: DownloadFileTypeEnum!) { getDownloadLink(id: $id, printId: $printId, source: $source,
fileType: $fileType) { ok output { link } errors { field messages } } }"""

# The generic answers every complex case starts from (same set as
# run_external_corpus.py), plus the per-case clicks recorded in CASE_CLICKS.
GENERIC_CLICKS = [
    {"question": "Choose the color", "button": "White"},
    {"question": "one color for everything?", "button": "One color for everything"},
    {"question": "does not fit the bed full size", "button": "Shrink to"},
    {"question": "How many copies", "button": "One copy"},
    {"question": "·", "button": "Slice and print"},
]
CASE_CLICKS = {}  # slug -> extra [[click]] rules, filled from verified local runs
# Verified 2026-10-27 (mock-tier flow runs): these three cases exceed the
# product's own intake limits, so the honest pinned expectation is the
# refusal receipt - the corpus case documents the limit behaviour.
CASE_EXPECT = {
    "fnaf-mask": {"status": "FAILED"},       # STL 36,467,384 B > 32 MiB intake cap
    "gyroid-surface": {"status": "FAILED"},  # STL 45,001,084 B > 32 MiB intake cap
    "chinese-dragon": {"status": "FAILED"},  # 3MF model XML > 400 MiB intake cap
}


def _open_direct(url, data=None, headers=None):
    """Open a URL without the ambient proxy (Printables' API drops proxied
    requests from some networks); retry a few times on connection errors."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, headers=headers or {})
    last = None
    for attempt in range(3):
        try:
            return opener.open(req, timeout=120)
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def printables_link(file_id, model_id):
    payload = json.dumps({"operationName": "GetDownloadLink",
                          "variables": {"id": str(file_id), "printId": str(model_id),
                                        "source": "model_detail", "fileType": "stl"},
                          "query": LINK_MUTATION}).encode()
    # The read is inside the retry: a connection can open fine and still
    # truncate the (small) GraphQL response mid-body, which raises
    # http.client.IncompleteRead on resp.read() - retry the whole
    # open-and-read, bounded like _open_direct, instead of crashing.
    data = None
    for attempt in range(3):
        try:
            with _open_direct(PRINTABLES_GQL, data=payload,
                              headers={"Content-Type": "application/json",
                                       "User-Agent": "Mozilla/5.0 Chrome/126",
                                       "Referer": "https://www.printables.com/"}) as resp:
                data = json.loads(resp.read().decode())
            break
        except Exception:  # noqa: BLE001 - retried, then re-raised
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    link = data["data"]["getDownloadLink"]
    if not link.get("ok"):
        raise RuntimeError(f"Printables refused a download link: {link.get('errors')}")
    return link["output"]["link"]


def download(url, dest):
    """Download to dest. Some CDNs drop long direct connections mid-file, so
    a short read resumes with an HTTP Range request instead of restarting -
    and a short file is never mistaken for a finished one."""
    written = 0
    expected = None
    stalled = 0
    for _attempt in range(60):
        before = written
        headers = {"User-Agent": "Mozilla/5.0 Chrome/126"}
        if written:
            headers["Range"] = f"bytes={written}-"
        try:
            with _open_direct(url, headers=headers) as resp:
                if written and resp.status != 206:  # Range ignored: start over
                    written = 0
                if expected is None:
                    total = resp.headers.get("Content-Range", "").rsplit("/", 1)[-1]
                    expected = int(total) if total.isdigit() else (
                        int(resp.headers["Content-Length"]) if resp.headers.get("Content-Length") else None)
                with open(dest, "ab" if written else "wb") as out:
                    while chunk := resp.read(1 << 20):
                        out.write(chunk)
                        written += len(chunk)
        except OSError:
            pass  # dropped mid-read: resume from what is on disk
        if expected is None or written >= expected:
            return
        stalled = stalled + 1 if written == before else 0
        if stalled >= 8:
            break
        print(f"  connection dropped at {written} of {expected} bytes, resuming")
    raise RuntimeError(f"{dest}: download kept truncating at {written} bytes")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_file(case, file_id, dest, want_bytes, want_sha):
    if dest.is_file() and dest.stat().st_size == want_bytes and sha256(dest) == want_sha:
        print(f"  ok (already fetched) {dest.name} {want_bytes}")
        return
    if case["site"] == "printables":
        url = printables_link(file_id, case["site_model_id"])
    elif case["site"] == "nasa":
        url = NASA_STL
    else:
        raise RuntimeError(f"no fetch route for site {case['site']}")
    download(url, dest)
    got = dest.stat().st_size
    if got != want_bytes or sha256(dest) != want_sha:
        raise RuntimeError(f"{dest}: fetched {got} bytes / sha mismatch - refusing a changed file")
    print(f"  fetched {dest.name} {got}")


def case_toml(case):
    clicks = GENERIC_CLICKS + CASE_CLICKS.get(case["slug"], [])
    lines = [f"# Complex corpus case for #458 - fetched, not committed. See complex_cases.toml.",
             f"license = {json.dumps(case['license'])}",
             f"fixture = {json.dumps(case['file'])}",
             f"description = {json.dumps(case['title'] + ' - target ' + case['target_domain'] + ' / ' + case['target_printer'])}",
             ""]
    for rule in clicks:
        lines += ["[[click]]", f"question = {json.dumps(rule['question'])}",
                  f"button = {json.dumps(rule['button'])}", ""]
    expect = {"status": "STARTED", **CASE_EXPECT.get(case["slug"], {})}
    lines.append("[expect]")
    for key, value in expect.items():
        lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path.home() / "print-buddy-complex-corpus"),
                        help="public corpus root (outside the repository)")
    parser.add_argument("--private-root", default=None,
                        help="also fetch private-tier cases into this separate root")
    args = parser.parse_args()
    manifest = tomllib.loads(MANIFEST.read_text())
    extras = {}
    for row in manifest.get("case.extra_file", []):
        pass  # tomllib nests these under each case; handled below
    for case in manifest["case"]:
        tier = case["tier"]
        if case["status"] != "ready":
            print(f"SKIP {case['slug']}: {case['status']} - {case.get('blocked_reason', '')[:100]}")
            continue
        if tier == "private" and not args.private_root:
            print(f"SKIP {case['slug']}: private tier (pass --private-root to fetch it locally)")
            continue
        root = Path(args.private_root if tier == "private" else args.root)
        folder = root / case["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        print(f"{case['slug']} -> {folder}")
        fetch_file(case, case.get("site_file_id"), folder / case["file"],
                   case["bytes"], case["sha256"])
        for extra in case.get("extra_file", []):
            fetch_file(case, extra["site_file_id"], folder / extra["name"],
                       extra["bytes"], extra["sha256"])
        (folder / "case.toml").write_text(case_toml(case))
        (folder / "ATTRIBUTION").write_text(
            f"{case['title']} by {case['author']}\nSource: {case['source_page']}\n"
            f"License: {case['license']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
