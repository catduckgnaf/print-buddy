# Third-party notice: Bambu Lab A1 OrcaSlicer profiles

`machine.json`, `process.json` and `filament.json` in this folder are flattened copies of OrcaSlicer's Bambu Lab (BBL) vendor profiles, with a few Print Buddy overrides. They are **not** original Print Buddy work, and the repository's MIT licence does not describe them.

- Source: [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) tag `v2.4.2`, commit `8500fcdccaa10b5099ac20d252af3a7c560046f1`, under `resources/profiles/BBL/`. OrcaSlicer is licensed under the GNU Affero General Public License v3 (`LICENSE.txt` at that commit). The BBL profiles came to OrcaSlicer from Bambu Studio by Bambu Lab, which is also AGPL-3.0.
- The vendor machine start, end, filament-change, timelapse and layer-change G-code is copied verbatim.
- Print Buddy changes only the keys listed in `print_buddy/printers/bambulab/facts.py` (`ORCA_OVERRIDES`, settings IDs).
- `scripts/bambu-templates.py --printer a1 --check` reproduces these files byte for byte from the source commit.

Whether these files may stay in this repository, and on what terms, is an open maintainer decision. See [Provenance and licence](../../../../docs/BAMBU-LAB.md#provenance-and-licence). Extracting, flattening or hash-pinning the files does not change their licence.
