## Summary and user impact

<!-- What changes for users or maintainers, and why is this change needed? -->

## Problem and cause

<!-- For a bug fix: describe the observed problem and the verified cause. For other changes, remove this section or write \"Not applicable.\" Do not guess at causes. -->

## Proposed changes

<!-- Describe the important behavior and code or documentation changes. Mention compatibility, migration, or safety effects when relevant. -->

## Type of change

- [ ] Bug fix
- [ ] User facing feature
- [ ] Maintenance or refactor
- [ ] Documentation
- [ ] CI or tests
- [ ] Breaking change

<!-- Select all that apply. Explain any breaking change in the section below. -->

## Verification and test results

<!-- List the relevant checks actually run and their results. Distinguish automated tests from manual or live checks. Do not mark a check as passed if it was not run. For unrun checks, state why. -->

- Checks run:
- Checks not run and why:

## Risks, limitations, and follow up

<!-- Note known risks, limitations, rollback or compatibility considerations, or write \"None known.\" Remove irrelevant prompts. -->

## Related issues

<!-- Link related issues. Use \"Fixes #N\" only when merging this PR should close the issue. -->

- Related:
- Fixes:
## Scope and acceptance criteria

<!-- State what is included and explicitly excluded. Link existing related work to avoid overlapping implementations. Keep this PR draft until required acceptance checks are complete. -->

- Acceptance criteria:
- Out of scope / remaining work:

## User-facing release note

<!-- Write for someone operating Print Handy, not someone reading the diff. Lead with what they can do or what no longer breaks. Group features, fixes, then technical details. State pending/draft status accurately. Write "Not applicable" for changes with no release-note impact. See docs/RELEASE-NOTES.md. -->

## Safety, compatibility and deployment

<!-- Identify changed confirmation, readiness, profile, clearance or artifact guards. Distinguish offline, real-slicer and live-printer verification. Document migration/rollback where relevant. Merging code does not authorize release publication, service deployment or physical operation. -->

- Safety/compatibility impact:
- Live checks or deployments performed (or "None"):

## Documentation and attribution

- [ ] Relevant setup, configuration and user documentation updated, or reason given below.
- [ ] Contributor credit and third-party licenses preserved where applicable; no invented coauthors.
- [ ] No credentials, private model files or personal runtime records included.

<!-- Leave unchecked items unchecked until verified. Use "Not applicable" with a reason rather than claiming an unrun check passed. -->

## Documentation impact

<!-- Required by contribution-policy. Choose each status and explain it. Do not check a box as a substitute for evidence. Features/configuration changes should update versioned docs in this PR. An internal-only change can explain why no documentation is needed. -->

Documentation: updated | not needed
Reason:
Wiki: updated | not applicable | deferred
Wiki reason:

<!-- Wiki updated: link the page. Deferred: link a tracking issue. Not applicable: explain why versioned docs cover the change and no separate wiki page needs updating. -->

## Surfaces and variables

<!-- Required by contribution-policy. For every configuration or settings variable this PR adds or changes, give a verdict for each surface below; a variable that exists on some surfaces and not others is how dead options and missing fields ship. A PR that adds or changes no variable chooses "not applicable" and says why. -->

Variables: checked | not applicable
Variables reason:

<!-- When "checked", name each added or changed variable and its verdict per surface: -->
<!-- - Defaults tree: present in the model/vendor defaults or settings.OPTIONAL_KEYS -->
<!-- - Environment loader: PRINT_HANDY__ name in .env.example and accepted by the loader, or file-only by design -->
<!-- - Web UI catalog: field added in print_handy/webui/catalog.py, or a recorded no-UI verdict with the reason -->
<!-- - Consuming code: the module or adapter that reads it, named -->
<!-- - Docs: docs/SETTINGS.md row and any surface doc updated -->
<!-- - Unraid templates: in-repo template updated, or the catduck-unraid-templates follow-up named -->

## Reviewer checklist

- [ ] User-visible behavior, configuration and limitations match the docs and release note.
- [ ] Documentation impact and wiki impact were reviewed, including any exemption or deferral.
- [ ] Tests cover the changed behavior; reported checks match actual evidence.
- [ ] Safety/authorization guards and contributor attribution are preserved.
- [ ] Behavior changes were checked against every adapter/connection in their scope (the printer-scope rule: a change for one printer family is verified for all families it touches, not only the one at hand).
- [ ] Registry/data changes keep their parity and drift tests green, or the exemption list is updated with a tracking reference.
- [ ] Required current-head CI checks pass before merge; no deployment or live action is implied.
