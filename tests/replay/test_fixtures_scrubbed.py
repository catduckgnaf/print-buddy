"""The recorded printer fixtures stay scrubbed: no addresses, credentials, serials or real file names."""
import json
import re

from .helpers import FIXTURES

FORBIDDEN = [
    (re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+(?:\.\d+)?\b"), "private IP address"),
    (re.compile(r"(?:api[_-]?key|password|passwd|ssid|(?:access|auth)[_-]?token|serial(?:[_-]?number)?)[\"']?\s*[:=]", re.I),
     "credential or serial assignment"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "uuid"),
    (re.compile(r"\b[0-9A-F]{2}(?::[0-9A-F]{2}){5}\b", re.I), "MAC address"),
]


def test_fixture_files_carry_nothing_private():
    files = sorted(p for p in FIXTURES.iterdir() if p.is_file() and p.name != "README.md")
    assert len(files) >= 10
    for path in files:
        text = path.read_text()
        for pattern, what in FORBIDDEN:
            assert not pattern.search(text), f"{path.name}: {what}: {pattern.search(text).group(0)!r}"


def test_recorded_file_names_are_neutral():
    names = []
    for job in json.loads((FIXTURES / "history_list.json").read_text())["result"]["jobs"]:
        names.append(job["filename"])
    for item in json.loads((FIXTURES / "files_list.json").read_text())["result"]:
        names.append(item["path"])
    printing = json.loads((FIXTURES / "objects_query.printing.json").read_text())["result"]["status"]
    names += [printing["print_stats"]["filename"], printing["virtual_sdcard"]["file_path"]]
    assert names and all("Replay-" in name for name in names), names
