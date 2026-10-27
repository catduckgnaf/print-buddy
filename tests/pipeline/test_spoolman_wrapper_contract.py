"""#387 contract: Spoolman HTTP lives in exactly one module.

print_buddy.core.spoolman_client is the only place that may open an HTTP
connection to Spoolman. This test fails CI if a future change reintroduces
a direct Spoolman call anywhere else:

- Rule 1: outside the wrapper, no function may combine a Spoolman API path
  literal (/api/v1/spool|filament|vendor|health) with a direct transport
  call (urlopen, urllib.request.Request, or another service's generic
  client: _get, request_json, _http, get_json). Naming a Spoolman path is
  fine — and necessary — where it is passed to an injected client callable
  whose default transport IS the wrapper (the /spool command layer in
  hermes/spool_sync.py, the runout answer flow, spool_lifecycle's injected
  clients): what is banned is pairing the path with a transport of its own.
- Rule 2: outside the wrapper, no function may combine Spoolman base-URL
  resolution (spoolman_url(...), SPOOLMAN_BASE, service_url("spoolman_url"))
  with a raw urlopen/Request.

Moonraker's /server/spoolman/spool_id endpoint is a Moonraker call, not a
Spoolman call, and is not restricted here.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "print_buddy"
WRAPPER = ROOT / "core" / "spoolman_client.py"

SPOOLMAN_PATH = re.compile(r"/api/v1/(?:spool|filament|vendor|health)\b")
BASE_RESOLUTION = re.compile(r"spoolman_url\(|SPOOLMAN_BASE|service_url\(\s*['\"]spoolman_url")
DIRECT_TRANSPORTS = {"urlopen", "Request", "_get", "request_json", "_http", "get_json"}
RAW_TRANSPORTS = {"urlopen", "Request"}


def _called_names(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _functions(path):
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = "\n".join(
                ast.get_source_segment(source, stmt) or "" for stmt in node.body)
            yield node.name, segment, node


def test_wrapper_exists_and_is_the_transport():
    source = WRAPPER.read_text()
    assert "urlopen" in source  # the one place raw Spoolman HTTP happens
    for name in ("request", "call", "get_spool", "list_spools", "health",
                 "SpoolmanUnavailable", "UNAVAILABLE_NOTICE"):
        assert name in source, f"spoolman_client is missing {name}"


def test_no_spoolman_path_with_direct_transport_outside_wrapper():
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if path == WRAPPER:
            continue
        for name, segment, node in _functions(path):
            if SPOOLMAN_PATH.search(segment):
                bad = DIRECT_TRANSPORTS & _called_names(node)
                if bad:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} {name}() pairs a Spoolman "
                        f"API path with direct transport {sorted(bad)}; route it through "
                        "print_buddy.core.spoolman_client (#387)")
    assert not violations, "\n".join(violations)


def test_no_spoolman_base_resolution_with_raw_transport_outside_wrapper():
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if path == WRAPPER:
            continue
        for name, segment, node in _functions(path):
            if BASE_RESOLUTION.search(segment):
                bad = RAW_TRANSPORTS & _called_names(node)
                if bad:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} {name}() resolves a Spoolman "
                        f"base URL and opens raw HTTP {sorted(bad)}; route it through "
                        "print_buddy.core.spoolman_client (#387)")
    assert not violations, "\n".join(violations)
