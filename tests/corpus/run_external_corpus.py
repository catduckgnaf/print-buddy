"""Run a shard of the external public model corpus through the fake-Discord harness."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace as S

# Ensure the repository's namespace package wins over any third-party `tests` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.corpus import harness

root = Path(os.environ["PRINT_HANDY_PRIVATE_CORPUS"]).resolve()
models = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".3mf", ".stl"})
shard_index, shard_count = int(os.environ["CORPUS_SHARD_INDEX"]), int(os.environ["CORPUS_SHARD_COUNT"])
results = []
workroot = Path(os.environ.get("CORPUS_WORK", "corpus-work"))
for index, model in enumerate(models):
    if index % shard_count != shard_index:
        continue
    case_dir = model.parent
    case = S(name=case_dir.name, dir=case_dir, model=model,
             data={"description": model.name},
             clicks=[{"question": "Choose the color", "button": "White"},
                     # Explicit monochrome consent for multipart and painted models.
                     {"question": "one color for everything?", "button": "One color for everything"},
                     # Pick the offered shrink, never silently approve a rotation/support tradeoff.
                     {"question": "does not fit the bed full size", "button": "Shrink to"},
                     {"question": "How many copies", "button": "One copy"},
                     {"question": "·", "button": "Slice and print"}],
             expect={"status": "STARTED"})
    started = time.monotonic()
    row = {"model": model.relative_to(root).as_posix(), "result": "PASS", "seconds": 0.0, "error": ""}
    try:
        run = harness.run_case(case, workroot / f"{shard_index}-{index}")
        harness.check_expectations(case, run)
        if not run.slice_starts:
            raise AssertionError("actual BackgroundSlice.start was never called")
        if len(run.slice_starts) != 1:
            raise AssertionError(f"expected one slice start, got {len(run.slice_starts)}")
        if not any(event[0] == "slice" for event in run.events):
            raise AssertionError("fake slicer was never called")
    except Exception as exc:
        row["result"] = "FAIL"
        # Preserve unanswered question text and buttons, not just the generic first line.
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["seconds"] = round(time.monotonic() - started, 2)
    results.append(row)
    print(json.dumps(row), flush=True)
out = Path(os.environ.get("CORPUS_RESULTS", "results.json"))
out.write_text(json.dumps(results, indent=2) + "\n")
if not results:
    raise SystemExit(f"shard {shard_index} selected no models")
