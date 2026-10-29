"""Read-only sliced layers (#624, stage 1)."""
import http.client
import json
import threading
from pathlib import Path

from print_handy import settings, webui_gate
from print_handy.webui import layers, server

PLATE = """G90
M83
G0 X10 Y10 Z0.2
;TYPE:Outer wall
;LAYER_CHANGE
G1 X20 Y10 E0.02
G1 X20 Y20 E0.02
;TYPE:Internal infill
G1 X12 Y12 E0.02
G1 X18 Y18 E0.02
;TYPE:Support
G1 X30 Y10 E0.02
G1 X36 Y10 E0.02
G0 X8 Y8
;LAYER_CHANGE
;TYPE:Inner wall
G1 Z0.4
G1 X11 Y11 E0.02
G1 X19 Y11 E0.02
"""

NOTE = "this file is a note, not a sliced plate\n"


def test_roles_colors_and_layer_range():
    parsed = layers.parse_gcode(PLATE)
    assert parsed["ok"]
    assert len(parsed["layers"]) == 2
    roles = {move["role"] for move in parsed["layers"][0]["moves"]}
    assert roles == {"perimeter", "infill", "support", "travel"}
    page = layers.render_plate(parsed, 0, title="swing")
    for role, color in layers.COLORS.items():
        if role == "other":
            continue
        assert f'data-role="{role}"' in page
        assert color in page
    assert 'stroke="#3d8bfd"' in page
    assert "Layer 1 of 2" in page
    assert "Previous layer" not in page
    assert "Next layer" in page
    last = layers.render_plate(parsed, 99, title="swing")
    assert "Layer 2 of 2" in last
    assert "Next layer" not in last
    assert "Previous layer" in last
    assert layers.clamp_layer(2, -4) == 0
    assert "Pause" not in page and "Exclude" not in page and "<button" not in page
    source = Path(layers.__file__).read_text(encoding="utf-8")
    assert "prepared_intake" not in source
    assert "print_control" not in source


def test_unreadable_file_is_an_error_with_no_drawing():
    parsed = layers.parse_gcode(NOTE)
    assert parsed == {"ok": False, "error": "this G-code has no extrusion to draw"}
    assert "layers" not in parsed
    page = layers.render_plate(parsed, 0, title="bad")
    assert "<svg" not in page
    assert "this G-code has no extrusion to draw" in page
    assert "Pause" not in page and "<button" not in page


def test_archive_paths_stay_inside_the_named_plate(tmp_path):
    job = tmp_path / "job-1"
    job.mkdir()
    (job / "plate_1.gcode").write_text(PLATE, encoding="utf-8")
    (job / "note.gcode").write_text(NOTE, encoding="utf-8")
    (tmp_path / "secret.gcode").write_text(PLATE, encoding="utf-8")
    (job / "JOB.json").write_text(json.dumps({
        "title": "Duplo swing",
        "gcode": "plate_1.gcode",
    }), encoding="utf-8")
    assert layers.resolve_plate(tmp_path, "job-1", "plate_1.gcode") == (job / "plate_1.gcode").resolve()
    assert layers.resolve_plate(tmp_path, "job-1", "note.gcode") is None
    assert layers.resolve_plate(tmp_path, "job-1", "../secret.gcode") is None
    assert layers.resolve_plate(tmp_path, "..", "secret.gcode") is None
    rows = layers.list_plates(tmp_path)
    assert rows == [{"job_id": "job-1", "file": "plate_1.gcode", "title": "Duplo swing"}]
    code, _ctype, body = layers.respond(tmp_path, "job-1/note.gcode", "0")
    assert code == 404
    code, ctype, page = layers.respond(tmp_path, "job-1/plate_1.gcode", "0")
    assert code == 200 and ctype.startswith("text/html")
    assert "Layer 1 of 2" in page and "#3d8bfd" in page
    code, _ctype, bad = layers.respond(tmp_path, "", "0")
    assert code == 200 and "Duplo swing" in bad


def test_server_serves_layers_and_a_disabled_webui_does_not_start(tmp_path):
    archive = tmp_path / "archive"
    job = archive / "job-1"
    job.mkdir(parents=True)
    (job / "plate_1.gcode").write_text(PLATE, encoding="utf-8")
    (job / "JOB.json").write_text(json.dumps({"title": "Duplo swing", "gcode": "plate_1.gcode"}),
                                  encoding="utf-8")
    local = tmp_path / "local.yaml"
    local.write_text(
        "paths:\n"
        f"  hermes_home: {tmp_path}/hermes\n"
        f"  archive: {archive}\n"
        "webui:\n  enabled: true\n  port: 8765\n",
        encoding="utf-8",
    )
    data = settings.load(local=local, environ={"PRINT_HANDY_CONFIG": str(local)})
    httpd = server.make_server(
        data, environ={"PRINT_HANDY_CONFIG": str(local)}, port=0,
        snapshot_func=lambda: {
            "version": "0.test", "host": "testhost", "ok": True,
            "printer": {"model": "flashforge.ad5x", "name": "Flashforge AD5X",
                        "vendor": "flashforge", "connection": "moonraker"},
            "bot": {"platform": "discord", "mode": "standalone", "ok": True,
                    "reason": "connected", "heartbeat": {"connected": True}},
            "listener": {"required": True, "ok": True, "reason": "alive"},
            "spoolman": {"bundled": True, "url": "http://127.0.0.1:8000", "ok": True,
                         "detail": "HTTP 200"},
            "services": {},
            "doctor": [{"label": "settings", "status": "ok", "detail": "fine"}],
        },
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        status, body = _get(port, "/")
        assert status == 200 and 'href="/layers"' in body
        status, body = _get(port, "/layers")
        assert status == 200 and "Duplo swing" in body and "plate_1.gcode" in body
        status, body = _get(port, "/layers/job-1/plate_1.gcode?layer=5")
        assert status == 200 and "Layer 2 of 2" in body and "<svg" in body
        status, body = _get(port, "/layers/job-1/../secret.gcode")
        assert status == 404
        assert webui_gate.decide({"webui": {"enabled": False, "host": "127.0.0.1", "port": 8080,
                                             "access_token_env": "WEBUI_ACCESS_TOKEN"}}) == 3
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read().decode()
    finally:
        conn.close()
