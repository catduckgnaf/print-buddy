# Complex slicer corpus (#458)

Real, complicated models for slicer diversity — the opposite of the
generated corpus in `tests/corpus/cases/` (tiny CC0 primitives from
`make_models.py`). The catalogue, measured stats and licences for every case
live in [`tests/corpus/complex_cases.toml`](../complex_cases.toml); stats were
measured from the downloaded files themselves, not copied from listings
(where a listing number disagrees with the file — e.g. the Stanford dragon
listing's 871,414 triangles describes the original scan, while the
distributed STL measures 318,460 — the manifest records the measured value
and notes the difference).

## Storage decision

The files are large (7–69 MB each, ~258 MB for the public set) and are
**not committed to this repository**, and public cases are not decimated or
shrunk to fit: the full-complexity mesh is the point of the case.

- Public cases are published as the `corpus-v2` release of
  `catduckgnaf/print-handy-corpus` (the same mechanism as the 171-model
  `corpus-v1`), as a tar with one folder per case plus `SHA256SUMS`, and the
  `model-corpus` workflow downloads and verifies both releases.
- Anyone can reproduce the same files with
  `tests/corpus/fetch_complex_corpus.py`, which downloads them pinned by the
  manifest's SHA256/byte size through the same eligible-site paths production
  intake uses (#462): Printables via its GraphQL `getDownloadLink` mutation
  (no token), NASA via its direct public link. A file whose hash or size has
  changed upstream is refused, not silently accepted.
- Private-tier cases (licence-flagged: CC BY-NC-SA and Standard Digital File
  License) are **never** committed, released or uploaded anywhere. They run
  locally only, from a separate private root; only their measured stats and
  run outcomes are recorded (in the manifest and on #458).

## Running

```bash
python tests/corpus/fetch_complex_corpus.py            # -> ~/print-handy-complex-corpus
COMPLEX_CORPUS_ROOT=~/print-handy-complex-corpus \
  python -m pytest tests/corpus/test_complex_corpus.py # manifest contract + hash check
COMPLEX_CORPUS_ROOT=~/print-handy-complex-corpus CORPUS_WORK=<disk dir> \
  python tests/corpus/run_complex_corpus.py            # flow runs, JSON results
```

`run_complex_corpus.py` drives each case through the fake-Discord harness
(mock slicer tier) with a printer state built from the case's manifest
target: the AD5X fixture state with printer name, bed and max height taken
from `printers/registry.toml`. 

**Honest limits of that mechanism:**

- The slicer vendor profile and the spool/slot layout in the state are still
  the fixture's (AD5X). Per-domain *geometry and height* are exercised;
  per-domain Orca/Bambu vendor profiles are not switched by the harness
  today, and slot counts are not remodelled for toolchangers or AMS units.
  Expectations therefore pin flow outcomes (started / scale / copies), not
  vendor-profile G-code.
- Real-Orca slicing of the fetched set is not part of per-PR CI: the cases
  also run in the weekly `model-corpus` workflow through its generic
  external-corpus flow (mock tier, default fixture state, like `corpus-v1`),
  and with their target states locally through the runner above. A case that has not been fetched is
  reported `NOT_FETCHED` / skipped with that reason — never silently dropped.
- One public case is `blocked-download` in the manifest (Smithsonian
  mammoth): the source offers no direct file link, its EDAN API requires a
  key this project does not hold, and its 3D API route is WAF-rejected. It
  stays in the manifest, with the evidence, until a maintainer with a
  Smithsonian API key fetches it through the official route.

## Private tier

```bash
python tests/corpus/fetch_complex_corpus.py --private-root ~/print-handy-private-corpus
COMPLEX_CORPUS_ROOT=~/print-handy-private-corpus CORPUS_WORK=<disk dir> \
  python tests/corpus/run_complex_corpus.py --tier private
```

The MakerWorld case (16 Color Polymaker Scientist) is `blocked-download`:
this codebase's MakerWorld route requires the account token file
`~/.config/bambu/token`, and without one the file cannot be obtained through
the eligible route. No scrape or captcha workaround is used, there or
anywhere else in this corpus.
