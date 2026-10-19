# Model source retrieval and MakerWorld completeness audit

Moved verbatim from profile AGENTS.md (2026-10-02 hardening) so it loads only for model links.

### Model-source retrieval: retrieve, do not improvise

MakerWorld and Printables are directly accessible from this profile. A model URL is a retrieval request, not permission to edit, generate, patch, or reverse-engineer unrelated local files.

**Fresh intake and hard source gate:** Every new plain URL event starts a fresh source-first job. The dispatcher inventories sources, honors an unambiguous profile hint, downloads and inspects actual named geometry, collects canonical colors once into that exact job, then asks local slice-only approval. Do not repeat saved choices or direct the user to /print-colors, paths, raw source indices or internal commands. Same-event delivery is idempotent; new-message jobs never inherit historical selections, permissions or sensor refusals. SLICE_APPROVED continues through the receipt's exact JOB.json using slice --approved, never another fetch. Source inspection and colors alone authorize neither slicing nor physical execution. Legacy explicit recovery may use fetch --select N --inspect-only, which downloads/audits without approval, color prompts, slicing, upload or launch. Normal selected fetch still needs explicit slicing approval. Never invent an access failure; report the actual failed stage. The completeness and physical launch gates below remain mandatory.

- **MakerWorld:** First search `~/3d-prints/` and the profile cache. If the artifact is absent, run `python3 -m print_buddy.core.model_job fetch '<MakerWorld URL>' --intake-id RECEIPT_ID`. The helper uses the host's saved Bambu authentication without exposing it. If the received URL does not include a `profileId`, use the web extractor only to identify the default/selected profile ID, append it to the URL, then run the helper. Resolve the model file, print profile, and author settings before discussing slicing. Never claim MakerWorld is inaccessible or ask the operator to download/upload it unless this exact retrieval and the local archive/cache both fail. If they do, state the actual failed stage and stop.
- **Printables:** First search the same archive/cache. If absent, run `python3 -m print_buddy.core.model_job fetch '<Printables URL>' --intake-id RECEIPT_ID`. Its public GraphQL path is verified working. Never ask the operator to download/upload a public Printables model unless that command and the archive/cache actually fail.
- **No unrelated edits:** Do not edit printer configuration, G-code, model files, skill files, scripts, or other local files merely because a source download is pending or failed. Diagnose and report a download failure instead. Source retrieval never authorizes a print start.
- **Affirmative follow-up and link memory:** When the operator replies affirmatively (e.g. "Let's do it", "Print it", "Go ahead", "Yes") or references a model previously recommended or linked in the conversation, never say you don't have the link or ask him to resend it. Resolve the model from recent conversation history and continue intake automatically.
- **Supports:** Preserve a compatible author-supplied file as-is. If the source's selected file or author instructions explicitly say supports are required and identify tree supports, tree supports may be generated during slicing. Do not independently decide that a model needs supports, substitute another support type, or add, remove, or tune supports based on your own geometry judgment. If the source does not expressly direct tree supports, stop and ask rather than inventing supports.

### MakerWorld mandatory two-pass completeness audit

Every MakerWorld link requires a two-pass completeness audit before slicing, uploading, or starting anything. A successful download of one selected profile is not evidence that the model is complete. The bot must prove whether the source is a single printable object or a multi-part project instead of printing the first attractive lump of plastic and discovering later that it was merely an organ awaiting the rest of the body.

**Pass 1, source-level inventory:** Retrieve and inspect the MakerWorld model metadata, every available print profile, plate, downloadable file, and source-visible assembly instruction. Record the exact names and counts. Look specifically for words and relationships such as `part`, `base`, `lid`, `mount`, `insert`, `left`, `right`, `top`, `bottom`, `A`, `B`, glue, screws, magnets, or assembly. Do not limit this check to the profile ID embedded in the operator's URL.

**Pass 2, artifact-level inventory:** Inspect the selected 3MF or archive internally before slicing. Count plates, build items, objects, component meshes, and named parts. Inspect thumbnails and model settings. If a single mesh may contain disconnected shells, calculate or inspect connected components rather than assuming one file means one physical part. Compare the artifact inventory against the source-level inventory and assembly description.

Before proceeding, state one of these conclusions with evidence:

- `Confirmed single-part model`, with the profile, plate, object, and connected-component counts.
- `Confirmed multi-part model`, followed by a durable checklist naming every required part and its planned print order.
- `Completeness unresolved`, followed by the exact missing metadata or contradiction. Do not slice or print while unresolved.

A multi-part source must retain its checklist until every required part is marked completed or the operator explicitly cancels the remaining parts. Never clear the session after only one component. The bed-clear control applies separately to each print job. This completeness audit is mandatory even when the operator says only `print this`, even when MakerWorld labels the selected artifact `no support`, and even when a prior cached file exists.

### Ambiguous multi-option model links

When a retrieved MakerWorld, Printables, or other model source offers multiple files, plates, variants, sizes, orientations, print profiles, or other selectable options and the operator has not identified one, make a best provisional selection only from source metadata and printer compatibility. Before slicing, uploading, selecting a G-code file, or starting a print, state **the exact option chosen** using its source-visible name and any relevant variant details, briefly state why it is the recommended default, and ask the operator to confirm or choose another listed option. Do not silently treat a site default, first file, or first plate as the operator's choice. This confirmation is separate from and does not replace the MakerWorld completeness audit and the later slicing, support, bed-clear, or print-start safety gates.

Example: “This source has `Standard`, `Slim`, and `Wall Mount` plates. I selected **Standard • right-hand orientation** as the compatible default. Confirm this version, or tell me which option you want.”

- **Catalogs with many profiles or files (e.g. 10+ or 50+ options):** Instruct the user to target the exact option by providing the direct profile URL with `#profileId-<id>`, or the exact profile title, plate name, or file name. Do not dump dozens of raw options into chat or buttons.
- **Model name and URL mismatch:** If the user specifies a model name (e.g. "Microfiber holder") that contradicts the title of the active or historical URL (e.g. "Miniature Baroque Frame"), never suggest reusing or re-fetching the historical URL. Stop and ask directly for the URL of the named model.
- **Cancellation / start-over commands:** When the user issues "STOP" or "Start over", immediately clear the conversational model target and wait for the new request. Never loop back to retry or re-fetch previous mismatched links.
