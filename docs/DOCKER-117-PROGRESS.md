# Issue 117 draft progress

Standalone bot work originated in zaheria985/print-buddy PR #3,
commit fba5727184dd8f0070e59c8f1fc088751142a003, integrated through #132.
The Docker foundation at 3bb0984250c20eb336d11ba1da06633950b45182
was reviewed for multi-stage packaging, separate deployment options and release
validation. This incremental implementation replaces binary downloads with
pinned Orca source builds; it is not a claim that the fork's entire Docker
implementation has been integrated or validated.

## Current increment

The Dockerfile defaults to standalone bot mode, uses an isolated Python venv,
nonroot runtime user and tini, and offers build arguments WITH_ORCA=true|false
and ORCA_CHANNEL=stable|alpha. Default WITH_ORCA=false avoids compiling Orca
unless explicitly selected. Bundled source pins are stable v2.4.2 and alpha
v2.5.0-alpha. These are independent of future application stable/development
image channels. Source build and runtime dependency closure are not yet proven.
The two source contract tests check declarations only, not runtime behavior.

## Remaining before supported delivery

- Reconcile Docker YAML/TOML slicer paths with /usr/bin/orca-slicer and specify
  fail-closed behavior without Orca. No remote slicer is promised.
- Replace legacy Compose with separate bot/listener services and coherent
  health contracts; external Spoolman default, bundled mode separately tested.
- Harden build context filtering without excluding the required print-feedback
  plugin. Complete configuration parity, first-run records and Unraid setup.
- Validate pinned stable source build and offline runtime fixture on Francium
  under the specifically approved bounded test. Alpha and ARM64 are unverified.
- Define stable/development branch and image promotion, persistence and rollback,
  and release evidence. No publishing/deployment is authorized by this draft.

The legacy Compose file and Docker configuration are not yet supported with
this candidate. Do not deploy it. No live Discord or printer validation performed.
