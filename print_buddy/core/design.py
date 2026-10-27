"""AI design with OpenSCAD (#388 Stage 1): create a new printable part from a description.

The engine owns the loop — prompt the model, extract the OpenSCAD source, sandbox-scan it,
render it, validate the mesh, render a preview — and nothing else. It never slices, uploads
or prints: a finished session's STL is handed to the ordinary prepared-intake flow by the
caller, and every gate after that is intake's own.

Safety shape (Stage 0 audit on #388, spike-proven):
- Model-authored SCAD may not contain import/include/use/surface statements at all. Those
  are OpenSCAD's only file-access statements, and the spike proved absolute paths, ``../``
  escapes and outside ``include<>`` all execute. The ban is token-level and runs before any
  subprocess starts.
- Every render passes ``--hardwarnings``: without it a warning-class defect (a hallucinated
  import of a missing file) exits 0 and silently produces a wrong part.
- The render runs in the session directory with a minimal environment, a wall-clock timeout
  and POSIX CPU/memory rlimits, following cad_split._run_openscad's discipline.

The engine takes a ``complete(messages) -> str`` callable and never knows the transport:
standalone resolves an OpenAI-compatible HTTP endpoint from [design]/[llm]; Hermes resolves
the plugin's ``ctx.llm`` lane with its registered ``print_design`` auxiliary task.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

MAX_SCAD_BYTES = 64 * 1024  # a single-file part design never needs more source than this
RENDER_TIMEOUT_S = 180
MAX_TURNS = 10
RETENTION_DAYS = 14
SESSIONS_DIRNAME = "design-sessions"

SLICE_LABEL = "Slice it"
CHANGE_LABEL = "Change it"
CANCEL_LABEL = "Cancel"
CHOICES = (SLICE_LABEL, CHANGE_LABEL, CANCEL_LABEL)

_FORBIDDEN = (
    ("import", re.compile(r"\bimport\s*\(", re.I)),
    ("include", re.compile(r"\binclude\s*[<(]", re.I)),
    ("use", re.compile(r"\buse\s*<", re.I)),
    ("surface", re.compile(r"\bsurface\s*\(", re.I)),
)
_FENCE = re.compile(r"```(?:openscad|scad)?\s*\n(.*?)```", re.S | re.I)
_SCAD_HINT = re.compile(
    r"\b(cube|sphere|cylinder|polyhedron|translate|rotate|scale|mirror|difference|union|"
    r"intersection|hull|minkowski|linear_extrude|rotate_extrude|module|function|\$fn)\b")


class DesignError(Exception):
    """A design turn failed in a way the user should be told about, in these words."""


# --------------------------------------------------------------------- sessions

def sessions_root(cache_dir) -> Path:
    return Path(cache_dir) / SESSIONS_DIRNAME


def _session_path(root: Path, session_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{8,40}", session_id or ""):
        raise DesignError("that design session id is not valid")
    return root / session_id


def _save(root: Path, session: dict) -> dict:
    folder = _session_path(root, session["id"])
    folder.mkdir(parents=True, exist_ok=True)
    session["updated_at"] = time.time()
    tmp = folder / "session.json.tmp"
    tmp.write_text(json.dumps(session, indent=1) + "\n", encoding="utf-8")
    tmp.replace(folder / "session.json")
    return session


def load_session(root, session_id):
    folder = _session_path(Path(root), session_id)
    try:
        data = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_session_for_owner(root, owner_key):
    """The newest non-finished session owned by this key, or None."""
    root = Path(root)
    if not root.is_dir():
        return None
    best = None
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        try:
            data = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("owner_key") != owner_key:
            continue
        if data.get("status") in ("cancelled", "handed_off"):
            continue
        if best is None or data.get("updated_at", 0) > best.get("updated_at", 0):
            best = data
    return best


def prune_old_sessions(root, days=RETENTION_DAYS, now=None):
    """Drop session folders whose last update is older than the retention window."""
    root = Path(root)
    if not root.is_dir():
        return 0
    cutoff = (now or time.time()) - days * 86400
    dropped = 0
    for folder in list(root.iterdir()):
        if not folder.is_dir():
            continue
        try:
            updated = json.loads((folder / "session.json").read_text(encoding="utf-8")).get("updated_at", 0)
        except (OSError, ValueError):
            updated = folder.stat().st_mtime
        if updated < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            dropped += 1
    return dropped


# --------------------------------------------------------------------- source handling

def extract_scad(reply) -> str:
    """The OpenSCAD source from a model reply: a fenced block, else the whole reply."""
    text = str(reply or "").strip()
    for block in _FENCE.findall(text):
        if _SCAD_HINT.search(block):
            return block.strip()
    if _SCAD_HINT.search(text) and "```" not in text:
        return text
    raise DesignError("the design model did not return any OpenSCAD code")


def scan_scad(source: str) -> None:
    """Refuse file-access statements before execution (Stage 0 sandbox spec)."""
    if len(source.encode("utf-8")) > MAX_SCAD_BYTES:
        raise DesignError(
            f"the design model returned {len(source.encode('utf-8'))} bytes of OpenSCAD; "
            f"the limit for one design file is {MAX_SCAD_BYTES} bytes, so nothing was run")
    for name, pattern in _FORBIDDEN:
        if pattern.search(source):
            raise DesignError(
                f"the design uses a '{name}' statement, which design files may not use: "
                "a design is one self-contained file and may not read other files. "
                "Nothing was run")


_SYSTEM_PROMPT = (
    "You are the design engine for a 3D printer helper. Answer with ONE OpenSCAD file and "
    "nothing else: no explanation, no markdown fences. Rules: millimetres; one self-contained "
    "file; put every dimension in a named top-level variable so it can be adjusted; use a "
    "sane $fn (24-64) for curves; the part must be a single solid resting on Z=0 unless the "
    "request says otherwise. You may NOT use import, include, use or surface statements — "
    "the file may not read other files. If you are given previous OpenSCAD and a change "
    "request, return the complete updated file. If you are given an OpenSCAD error, return "
    "the complete corrected file."
)


def _messages(session, instruction, previous_scad=None, error=None):
    parts = [f"Design request: {session['description']}"]
    if previous_scad:
        parts.append(f"Current OpenSCAD (turn {session['turns']}):\n{previous_scad}")
        parts.append(f"Change requested: {instruction}")
    if error:
        parts.append(f"The previous file failed to render. OpenSCAD said:\n{error}\n"
                     "Return the complete corrected file.")
    return [{"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)}]


# --------------------------------------------------------------------- rendering

def _limits(timeout_s):
    def apply():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout_s) + 5, int(timeout_s) + 10))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    return apply


def render_scad(scad_path: Path, stl_path: Path, *, timeout_s=RENDER_TIMEOUT_S, runner=None):
    """Render one SCAD file to STL. Returns (ok, error_text). Never raises for a bad design."""
    exe = shutil.which("openscad")
    if not exe:
        raise DesignError("OpenSCAD is not installed on this machine (no openscad on PATH), "
                          "so designs cannot be rendered")
    cmd = [exe, "--hardwarnings", "-o", str(stl_path), "--export-format", "binstl", str(scad_path)]
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(scad_path.parent)}
    run = runner or subprocess.run
    kwargs = {"capture_output": True, "text": True, "timeout": timeout_s,
              "cwd": str(scad_path.parent), "env": env}
    if runner is None and os.name == "posix":
        kwargs["preexec_fn"] = _limits(timeout_s)
    try:
        proc = run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return False, f"OpenSCAD did not finish within {timeout_s} seconds (timeout)"
    except TypeError:
        # An injected test runner may not accept every subprocess keyword.
        proc = run(cmd)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0 or "ERROR:" in combined or not stl_path.is_file() \
            or stl_path.stat().st_size < 84:
        lines = [line for line in combined.splitlines() if line.strip()]
        return False, "\n".join(lines[-6:]) or f"OpenSCAD exited with code {proc.returncode}"
    return True, ""


def validate_stl(stl_path: Path) -> dict:
    """Geometry facts for a rendered STL; raises DesignError on an unusable mesh."""
    from .geometry_layout import describe_triangles
    from .orca_adapter import read_stl_triangles
    info = describe_triangles(read_stl_triangles(stl_path))
    volume = info.get("abs_volume_mm3")
    if not info.get("dimensions_mm") or not volume or float(volume) <= 0:
        raise DesignError("the rendered file has no solid volume (empty or non-watertight "
                          "mesh), so there is nothing to print")
    return info


# --------------------------------------------------------------------- transports

def resolve_http_config(cfg) -> dict | None:
    """The effective standalone design endpoint: [design] first, [llm] as the fallback."""
    design = (cfg or {}).get("design") or {}
    llm = (cfg or {}).get("llm") or {}
    chat_url = str(design.get("chat_url") or llm.get("chat_url") or "").strip()
    model = str(design.get("model") or llm.get("model") or "").strip()
    if not chat_url or not model:
        return None
    return {"chat_url": chat_url, "model": model,
            "api_key_env": str(design.get("api_key_env") or llm.get("api_key_env")
                               or "LLM_API_KEY"),
            "timeout_s": int(design.get("timeout_s") or 180)}


def http_complete(cfg, messages, *, opener=None):
    """One design model call over an OpenAI-compatible endpoint. Returns the reply text."""
    import urllib.request
    resolved = resolve_http_config(cfg)
    if resolved is None:
        raise DesignError("design is enabled but no model endpoint is configured: "
                          "set [design] chat_url and model, or the [llm] values they inherit")
    key = os.environ.get(resolved["api_key_env"]) or ""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({"model": resolved["model"], "messages": messages,
                       "max_tokens": 4000, "temperature": 0.3}).encode()
    req = urllib.request.Request(resolved["chat_url"], data=body, headers=headers, method="POST")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=float(resolved["timeout_s"])) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise DesignError(f"the design model call failed: {exc}") from None
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        raise DesignError("the design model returned a reply with no message content") from None


async def hermes_complete(llm, messages, *, timeout_s=180):
    """One design model call through the Hermes plugin LLM lane (ctx.llm).

    The model is the plugin's registered ``print_design`` auxiliary task: the
    operator pins provider/model/reasoning for it in the profile's
    ``auxiliary.print_design`` block; with no pin it follows the profile's
    active model. A trust-gate refusal (an operator who has not granted a
    pin the call needs) surfaces as a plain DesignError, never a crash.
    """
    kwargs = {"messages": messages, "task": "print_design", "purpose": "print-design",
              "timeout": timeout_s, "max_tokens": 4000, "temperature": 0.3}
    try:
        acomplete = getattr(llm, "acomplete", None)
        if callable(acomplete):
            result = await acomplete(**kwargs)
        elif callable(getattr(llm, "complete", None)):
            result = await asyncio.to_thread(llm.complete, **kwargs)
        else:
            raise DesignError("this Hermes version does not offer the plugin LLM lane "
                              "(ctx.llm), so design has no model in Hermes mode")
    except DesignError:
        raise
    except Exception as exc:
        if "Trust" in type(exc).__name__ or "trust" in str(exc).lower():
            raise DesignError(
                "Hermes refused the design model call (plugin LLM trust gate). "
                "Pin the design model in the profile's auxiliary.print_design block, "
                "or grant the print-feedback plugin a model override in config.yaml") from None
        raise DesignError(f"the design model call failed: {exc}") from None
    text = getattr(result, "text", result)
    return str(text or "")


# --------------------------------------------------------------------- the engine

class DesignEngine:
    """Runs design sessions against an injected model callable and OpenSCAD."""

    def __init__(self, cache_dir, complete, *, cfg=None, runner=None, preview=None,
                 render_timeout_s=RENDER_TIMEOUT_S):
        self.root = sessions_root(cache_dir)
        self.complete = complete
        self.cfg = cfg or {}
        self.runner = runner
        self.preview = preview  # callable(stl_path) -> preview path; None uses render_preview
        self.render_timeout_s = render_timeout_s
        design = self.cfg.get("design") or {}
        self.repair_attempts = int(design.get("repair_attempts", 3))

    # -- session lifecycle -------------------------------------------------

    def start_session(self, owner_key, chat_id, description):
        prune_old_sessions(self.root)
        session = {"id": uuid.uuid4().hex[:12], "owner_key": owner_key,
                   "chat_id": str(chat_id), "description": str(description)[:500],
                   "status": "active", "turns": 0, "created_at": time.time(),
                   "updated_at": time.time(), "scad": None, "stl": None,
                   "preview": None, "geometry": None}
        return _save(self.root, session)

    def cancel(self, session):
        session["status"] = "cancelled"
        return _save(self.root, session)

    def mark_handed_off(self, session):
        session["status"] = "handed_off"
        return _save(self.root, session)

    def awaiting_revision(self, session):
        session["status"] = "awaiting_revision"
        return _save(self.root, session)

    def current_scad(self, session):
        name = session.get("scad")
        if not name:
            return None
        path = _session_path(self.root, session["id"]) / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    # -- one turn ----------------------------------------------------------

    async def _call(self, messages):
        result = self.complete(messages)
        if inspect.isawaitable(result):
            result = await result
        return str(result or "")

    def _render_and_validate(self, session, source):
        folder = _session_path(self.root, session["id"])
        folder.mkdir(parents=True, exist_ok=True)
        turn = session["turns"] + 1
        scad_path = folder / f"turn-{turn}.scad"
        stl_path = folder / f"turn-{turn}.stl"
        scad_path.write_text(source, encoding="utf-8")
        ok, error = render_scad(scad_path, stl_path, timeout_s=self.render_timeout_s,
                                runner=self.runner)
        if not ok:
            return None, error
        try:
            info = validate_stl(stl_path)
        except DesignError as exc:
            return None, str(exc)
        preview_path = None
        try:
            preview_path = self._make_preview(session, stl_path, turn)
        except Exception:
            preview_path = None  # a failed preview never fails the turn
        session["turns"] = turn
        session["scad"] = scad_path.name
        session["stl"] = stl_path.name
        session["preview"] = Path(preview_path).name if preview_path else None
        session["geometry"] = info
        session["status"] = "active"
        _save(self.root, session)
        return {"session": session, "scad_path": scad_path, "stl_path": stl_path,
                "preview_path": preview_path, "geometry": info, "scad": source}, ""

    def _make_preview(self, session, stl_path, turn):
        if self.preview is not None:
            return self.preview(stl_path)
        from . import render_preview
        bed = (self.cfg.get("printer") or {}).get("bed_mm")
        made = render_preview.render(str(stl_path), bed=bed)
        if not made:
            return None
        dest = _session_path(self.root, session["id"]) / f"turn-{turn}.png"
        shutil.copyfile(made, dest)
        return str(dest)

    async def run_turn(self, session, instruction):
        """One design turn: model -> scan -> render -> validate, with bounded repairs.

        Returns the turn result dict. Raises DesignError with user-ready words
        when the turn fails; the session keeps its previous good turn, if any.
        """
        if session["turns"] >= MAX_TURNS and session.get("scad"):
            raise DesignError(f"this design session has had its {MAX_TURNS} turns; "
                              "slice it or cancel and start a new design")
        previous = self.current_scad(session)
        error = None
        attempts = 1 + self.repair_attempts
        last_error = ""
        for attempt in range(attempts):
            reply = await self._call(_messages(session, instruction, previous, error))
            source = extract_scad(reply)
            scan_scad(source)  # a sandbox refusal is not repaired by asking again
            result, last_error = await asyncio.to_thread(
                self._render_and_validate, session, source)
            if result is not None:
                return result
            error = last_error
            previous = source
            if attempt + 1 >= attempts:
                break
        raise DesignError(
            f"OpenSCAD could not render the design after {attempts} attempt(s). "
            f"Last error: {last_error}")


def summary_text(result) -> str:
    """The measured-facts line posted with a design preview."""
    info = result["geometry"]
    dims = " × ".join(f"{float(v):g}" for v in info["dimensions_mm"])
    volume = info.get("abs_volume_mm3")
    return (f"{dims} mm, {float(volume):.0f} mm³, {info['shell_count']} shell(s), "
            f"{'watertight' if info['watertight'] else 'NOT watertight'}, "
            f"{'manifold' if info['manifold'] else 'NOT manifold'}")
