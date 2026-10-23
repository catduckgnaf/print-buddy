# KiCad 3D models as slicing inputs and fixtures (evaluation for #122)

**Recommendation: defer.** Print Buddy should not accept KiCad boards or projects as Discord input, and should not add KiCad as a runtime, CI or test dependency now. The export path works: KiCad 9 writes an STL that Print Buddy's existing intake, fit probe, real OrcaSlicer slice and slice guard all accept unchanged. But a KiCad board adds nothing that the stdlib corpus generator or the planned OpenSCAD fixtures (#118) cannot produce more cheaply and more reproducibly, and it brings a 350 to 670 MB toolchain whose geometry changes between KiCad versions. Revisit only for a concrete PCB-shaped printing need (see [Follow-up scope](#follow-up-scope-if-revisited)). #118 can proceed.

Everything below was run in a disposable Ubuntu 24.04 cloud sandbox. Nothing contacted a printer, Moonraker, Spoolman, Discord or the Dysprosium and Francium hosts, and no Docker container was used. Results are split into three levels: export and geometry, slicer and toolpath, and physical print. The last level was not tested.

## What was tested

| Tool | Version | Source |
| --- | --- | --- |
| KiCad (host) | 7.0.11+dfsg-1build4 | Ubuntu 24.04 `universe`, `apt-get install --no-install-recommends kicad` |
| KiCad (chroot) | 9.0.3+dfsg-1 | Ubuntu 25.10 (questing) `universe`, installed the same way in a `debootstrap --variant=minbase` chroot, because the KiCad PPA and Flathub were not reachable from the sandbox |
| OrcaSlicer | 2.4.2 | Upstream `OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage`, extracted. Same release as the production Flathub track. Templates: `print_buddy/templates/orca/flashforge_ad5x` |
| trimesh, cascadio | 5.1.1, 0.1.1 | pip, in a throwaway venv, only for the STEP-to-STL conversion check |
| Python | 3.13.16 | sandbox |

### Representative board

This is a hand-written 50 × 30 mm two-layer board with four 3.2 mm mounting holes. It is own work with no third-party geometry. KiCad 7 and KiCad 9 both load it.

```lisp
(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers
    (0 "F.Cu" signal) (31 "B.Cu" signal)
    (36 "B.SilkS" user "B.Silkscreen") (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user) (39 "F.Mask" user)
    (44 "Edge.Cuts" user) (49 "F.Fab" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (gr_rect (start 0 0) (end 50 30) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
  (gr_circle (center 4 4) (end 5.6 4) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
  (gr_circle (center 46 4) (end 47.6 4) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
  (gr_circle (center 4 26) (end 5.6 26) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
  (gr_circle (center 46 26) (end 47.6 26) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts")))
```

A second variant, `parts.kicad_pcb`, adds two footprints to the same board:

* `U1` has an 8 × 6 × 4 mm block model at `${KIPRJMOD}/block.step`. The block was itself exported from a tiny KiCad board, so it is also own work.
* `R1` points at a stock KiCad library model, `${KICAD9_3DMODEL_DIR}/Resistor_THT.3dshapes/R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal.step`. The library is not installed, so this model is missing on purpose.

## KiCad CLI export capabilities

`kicad-cli pcb export` subcommands that produce 3D geometry:

| Format | KiCad 7 | KiCad 8 | KiCad 9 | Orca 2.4.2 CLI reads it | Notes |
| --- | --- | --- | --- | --- | --- |
| STEP | yes (tested) | yes (docs) | yes (tested) | **no** | B-rep, mm. The header carries a timestamp and file name, so it is not byte-reproducible |
| VRML | no | yes (docs) | yes (tested) | **no** | Default `--units in`, so it must be forced to `mm` |
| GLB | no | yes (docs) | yes (tested) | **no** | glTF units are metres. Not byte-identical across runs |
| STL | no | no | **yes (tested)** | **yes** | ASCII STL, mm. Byte-identical across runs on the same KiCad version |
| PLY | no | no | yes (tested) | **no** | |
| BREP, XAO | no | no | yes (tested) | **no** | OCCT-native B-rep, only useful to CAD tools |

KiCad 7 and 9 were read from `kicad-cli pcb export --help` in the sandbox. KiCad 8 was **not run**; its column comes from the KiCad 8.0 CLI reference (`kicad-doc` branch `8.0`, `src/cli/cli.adoc`).

The KiCad 9 3D exporters share these options: `--board-only`, `--no-components`, `--component-filter`, `--no-dnp`, `--no-unspecified`, `--include-tracks/pads/zones/silkscreen/soldermask`, `--fuse-shapes`, `--subst-models`, and the origin options.

Print Buddy's intake accepts only `.3mf` and `.stl` (`orca_adapter.source_triangles`, `tests/corpus/harness.py` `MODEL_FILE_EXTS`). Orca 2.4.2's CLI rejected every other KiCad output with:

```text
k9-board.step: Unknown file format. Input file must have .stl, .obj, .amf(.xml) extension.
run found error, return -6, exit...
```

The same failure (exit 250) happened for `.step` from KiCad 7 and 9, and for `.ply`, `.glb` and `.wrl`. So the only direct path is **KiCad ≥ 9 → STL**. KiCad 7 and 8 need an extra STEP → STL converter.

## Results, level 1: export and geometry

Commands (KiCad 9 ran in the chroot, with the work directory bind-mounted at `/work`):

```bash
kicad-cli version                                                       # 7.0.11 / 9.0.3
kicad-cli pcb export step --board-only -o host7-board.step demo.kicad_pcb               # KiCad 7, exit 0
kicad-cli pcb export stl  --board-only -f -o k9-board.stl  demo.kicad_pcb               # KiCad 9, exit 0
kicad-cli pcb export step|glb|ply|brep --board-only -f -o k9-board.<ext> demo.kicad_pcb # KiCad 9, exit 0
kicad-cli pcb export vrml --units mm -f -o k9-board.wrl demo.kicad_pcb                  # KiCad 9, exit 0
kicad-cli pcb export stl [--fuse-shapes] -f -o k9-parts.stl parts.kicad_pcb             # KiCad 9, exit 2 (missing R1 model)
```

The STEP → STL conversion for KiCad 7 and 8 hosts used trimesh with the cascadio STEP loader. Note the units: the loaded mesh is in **metres** (`mesh.units == "meters"`). Without the `× 1000` the plate becomes 0.05 × 0.03 mm.

```python
mesh = trimesh.load("host7-board.step", force="mesh")
mesh.apply_scale(1000.0); mesh.merge_vertices(); mesh.export("host7-board-cascadio.stl")
```

Each STL was read with Print Buddy's own `orca_adapter.read_stl_triangles`. The checker then reported bounds and signed volume, flagged any directed edge without a matching opposite edge (holes or flipped faces), and counted connected shells:

| Mesh | Triangles | Bounds (mm) | Volume (mm³) | Closed, consistent winding | Shells |
| --- | --- | --- | --- | --- | --- |
| KiCad 9 `--board-only` STL | 412 | x 0–50, y −30–0, z 0–**1.51** | 2216.98 | yes | 1 |
| KiCad 7 STEP → cascadio STL | 668 | x 0–50, y −30–0, z 0–**1.60** | 2348.74 | yes | 1 |
| KiCad 9 STEP → cascadio STL | 668 | x 0–50, y −30–0, z 0–1.51 | 2216.62 | yes | 1 |
| KiCad 9 parts STL (with or without `--fuse-shapes`) | 724 | x 0–50, y −30–0, z 0–5.505 | 2401.98 | yes | **2** (board z 0–1.51, block z 1.595–5.505) |

The expected volume for a 1.51 mm plate with four 3.2 mm holes is 2216.4 mm³, which matches. Findings:

1. **Board-only geometry is clean.** It is one closed, consistently wound shell, and KiCad 9's STL is byte-identical across repeated runs (sha256 `724ffd20…3645` for the board above).
2. **The geometry depends on the KiCad version.** KiCad 7 STEP makes the board body 1.60 mm, the nominal stackup thickness. KiCad 9 makes it 1.51 mm: the dielectric only, with copper and mask left out unless you pass `--include-*`. A fixture regenerated on a different KiCad major version changes shape, so a fixture would have to be committed as the mesh, not regenerated in CI.
3. **Y is flipped and negative.** KiCad's Y-down board space becomes Y −30–0. Print Buddy recentres every STL on the bed, so this caused no problem, but it is another way the output differs from authored printable models.
4. **Component models do not make printable solids.** The block model sits on the copper surface (z 1.595), 0.085 mm above the 1.51 mm board body, so the result is two disjoint shells. `--fuse-shapes` changed nothing because they do not touch.
5. **Missing 3D models are silently dropped.** KiCad 9 prints `Could not add 3D model for R1. File not found: …`, exits **2**, and still writes the STL without R1. KiCad 7 exits **0** with the same warning. Before a project file existed next to the board, `${KIPRJMOD}` did not resolve either and U1 was dropped too. Any automated export would have to fail on these warnings, not trust the exit code.

## Results, level 2: slicer and toolpath (offline)

Raw Orca CLI, with the same flags `tests/slicer/test_orca_real.py` uses:

```bash
orca-slicer --load-settings "$T/machine.json;$T/process.json" --load-filaments "$T/filament.json" \
  --arrange 1 --orient 0 --ensure-on-bed --allow-newer-file --slice 0 --outputdir "$OUT" k9-board.stl
```

| Input | Exit | G-code | Layers | Filament | Estimated time |
| --- | --- | --- | --- | --- | --- |
| KiCad 9 board STL | 0 | `plate_1.gcode` | 6 | 2.89 g | 4 m 44 s |
| KiCad 9 parts STL (two shells) | 0 | `plate_1.gcode` | 23 | 3.05 g | 6 m 19 s |
| any `.step`, `.ply`, `.glb`, `.wrl` | 250 | none | | | |

At the AD5X profile's 0.24 mm layer height, the 1.51 mm plate becomes 6 layers (1.44 mm). The Z quantisation is visible, as it would be for any thin plate.

**Print Buddy pipeline.** Each mesh was placed as a case in a local private corpus (`PRINT_BUDDY_PRIVATE_CORPUS`, outside the checkout) and run through `tests/corpus/test_corpus.py::test_discord_flow`. That covers the real Discord intake hook, the colour and copies prompts, the fit probe, `BackgroundSlice`, the slice guard and the `print_next` start gates against the stub print-now script. Each case expected `source_kind = ".stl"`, `source_size_mm = [50, 30, z]`, one G-code, scale 1.0, supports off and one slot.

| Case | Mock tier (fake Orca) | Real tier (Orca 2.4.2) |
| --- | --- | --- |
| `kicad9-board-stl` | passed | passed |
| `kicad7-step-to-stl` | passed | passed |
| `kicad9-parts-stl` | passed | passed |

```bash
PRINT_BUDDY_PRIVATE_CORPUS=$PRIVATE python3 -m pytest -q tests/corpus/test_corpus.py::test_discord_flow -k kicad
PATH=$SHIM:$PATH PRINT_BUDDY_PRIVATE_CORPUS=$PRIVATE PRINT_BUDDY_REAL_SLICER=1 \
  xvfb-run -a python3 -m pytest -v -s tests/corpus/test_corpus.py::test_discord_flow -k kicad
```

`tests/corpus/conftest.py` pins the home Orca command, `flatpak run com.orcaslicer.OrcaSlicer`. Flathub was unreachable from the sandbox, so `$SHIM` holds a one-line `flatpak` script that runs the extracted AppImage. Control runs with the same setup:

* The public corpus passed in the real tier (72 passed).
* `PB_ORCA_CMD=<AppRun> PRINT_BUDDY_REAL_SLICER=1 pytest tests/slicer` passed (10 passed).
* The offline suite passed (1195 passed, 36 skipped).

The two-shell parts mesh also passed, so the pipeline accepts what KiCad produces even when the result is not a sensible print. That is a reason not to feed it component exports, not evidence that they work.

## Results, level 3: physical print

Not tested. The sandbox has no printer access, and the issue forbids live printer actions. No claim is made about how the plate prints, bed adhesion of a 1.5 mm part, or hole accuracy.

## Dependencies and licensing

* **Install size.** `--no-install-recommends kicad` added 27 packages and 346 MB on an Ubuntu 24.04 host that already had GTK and Mesa, and 202 packages and 673 MB on a minimal Ubuntu 25.10 base. The `kicad` package alone is about 128 MB (9.0.3) to 143 MB (7.0.11) installed. The stock 3D model library, `kicad-packages3d`, is 5.7 GB installed and was not installed.
* **Distribution versions.** Ubuntu 24.04 `apt` gives **7.0.11**, which has no STL export. Ubuntu 25.10 `apt` gives **9.0.3** (both verified). Other routes to KiCad 9 were not testable here: the `ppa:kicad/kicad-9.0-releases` PPA, Flathub `org.kicad.KiCad` (run as `flatpak run --command=kicad-cli org.kicad.KiCad`; like Orca, its sandbox would not see `/tmp`), and the Arch or Fedora repositories.
* **STEP converter for KiCad 7 and 8.** trimesh (MIT) plus cascadio (MIT, about 99 MB with bundled Open CASCADE, which is LGPL-2.1 with an exception). FreeCAD or gmsh would also work but are larger.
* **KiCad itself** is GPL-3.0-or-later. Running `kicad-cli` puts no licence on the user's design or on files exported from it, and Print Buddy would not redistribute KiCad.
* **KiCad libraries** (symbols, footprints, 3D models) are CC-BY-SA 4.0 with an exception that waives article 3 (attribution and share-alike) for designs and "any generated files which use data provided as part of the Licensed Material" (kicad-packages3D `LICENSE.md`). The exception does not cover redistributing the library files themselves as a collection. A board exported with stock component models is therefore probably redistributable, but its licence label would not match the corpus allowlist (`tests/corpus/test_corpus.py` `PUBLIC_LICENSE`), and it would need a judgement call per fixture. Board-only exports of an own-work board have no third-party content and could be committed as `own work`.
* **Third-party demo boards** (the `kicad-demos` package, community projects) have mixed licences. Own-work boards avoid that question entirely.

## Intake options compared

| Option | Verdict | Why |
| --- | --- | --- |
| Accept `.kicad_pcb` or a project in Discord and export on the host | **Reject** | It needs KiCad ≥ 9 on the bot host, which Ubuntu 24.04 cannot provide from `apt`. It would run a large C++ parser on untrusted uploads. Projects can reference arbitrary local model paths through `${VAR}` expansion, and missing models still produce a "successful" STL. Export time and size are unbounded. And Discord users want enclosures, not PCB slabs. |
| Accept exported STEP, VRML, GLB or PLY | **Reject** | Orca 2.4.2's CLI reads none of them. Supporting them means adding a CAD kernel to intake, with unit traps (GLB and cascadio in metres, VRML in inches by default). |
| Users export STL from KiCad themselves and upload it | **Already supported** | A KiCad 9 STL is an ordinary STL, and the existing STL intake handled it end to end. Nothing to build. |
| Use KiCad offline to generate test fixtures | **Defer** | It works, but the board-only output is a thin extruded outline with holes, which `tests/corpus/make_models.py` can generate with the standard library alone, deterministically and on any machine. Component exports are multi-shell and depend on a 5.7 GB library. |

## Compared with OpenSCAD fixtures (#118)

| | KiCad | OpenSCAD |
| --- | --- | --- |
| Designed for | PCB layout; 3D is a by-product | Printable parametric solids |
| Direct STL from the CLI | KiCad ≥ 9 only | Yes (`openscad -o x.stl`), every packaged version |
| Ubuntu 24.04 `apt` | 7.0.11 (no STL) | 2021.01 (`openscad` package about 10 MB installed) |
| Shapes it can express | Extruded board outlines; components only through external models | Arbitrary CSG: overhangs, fit and fail cases, tolerances for #83 |
| Output stable across versions | No (1.60 → 1.51 mm board body between 7 and 9) | Not checked here; #118 should verify |
| Licensing of sources | Own-work boards are clean; library models need the exception | Own-work `.scad` is clean |

OpenSCAD fits the fixture goal better on every row. Two things this evaluation suggests #118 should carry over: commit the exported mesh alongside the source and compare against it, so a toolchain upgrade cannot silently change a fixture, and check the tool version with a clear message when it is missing.

## Minimum tooling on Dysprosium and Francium

These hosts were **not inspected**; this session has no access to them. Because the recommendation is to defer, **nothing needs to be installed on either host now**. If KiCad is revisited, each host would need:

```bash
kicad-cli version            # must print 9.x or newer for native STL export
kicad-cli pcb export stl --help | grep -q -- --board-only && echo "STL export available"
```

With KiCad older than 9, also needed: a STEP → STL converter (trimesh with cascadio, FreeCAD or gmsh) with an explicit metres-to-millimetres check. With Flatpak KiCad, exports must be written inside the checkout or `$HOME` (for example `.slicer-work/`), as for Orca, because the sandbox cannot see the host's `/tmp`.

## Follow-up scope if revisited

Reopen only for a concrete need, such as test-fitting a printed enclosure or spacer against a real board outline. Keep the scope bounded:

1. Board-only STL from KiCad ≥ 9, generated offline by a script under `scripts/`. Never at runtime, never from Discord uploads, never in CI.
2. Commit the own-work `.kicad_pcb` and the exported `model.stl` together as a corpus case with `license = "own work"`, and record the KiCad version and sha256 in `case.toml`.
3. Make the export script fail on any `Could not add 3D model` line and on a non-zero exit, and reject meshes with more than one shell.
4. Add no new intake formats and no runtime dependency.

## Reproduction notes

* The KiCad 9 chroot: `debootstrap --variant=minbase --components=main,universe questing /opt/kicad9-root http://archive.ubuntu.com/ubuntu`, then `apt-get install --no-install-recommends kicad` inside it. `debootstrap` 1.0.134 on Ubuntu 24.04 needs a `questing → gutsy` script symlink.
* Orca: `OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage --appimage-extract`. It needs `libwebkit2gtk-4.1-0` and `xvfb-run` on a headless host.
* Generated meshes and G-code stayed in the session scratchpad and the ignored `.slicer-work/`. None are committed.
