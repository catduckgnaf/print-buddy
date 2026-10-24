"""print_alert_buttons: cause text, buttons, click safety. Offline; no printer traffic."""
from unittest.mock import patch

from print_buddy.hermes import print_alert_buttons as pab
from print_buddy.hermes import moonraker_event_listener as mel

LIVE = ("Nozzle hit bed or part detachment. Weight 1512>1500.0. Z=10. FIRMWARE_RESTART. "
        "https://wiki.zmod.link/Global/#nozzle_control\nOnce the underlying issue is corrected, use the\n")


def test_explain_nozzle_collision_live_text():
    out = pab.explain(LIVE)
    assert "1512 g" in out and "1500 g" in out and "Z=10 mm" in out and "blob" in out


def test_explain_old_format_and_unknown_and_empty():
    assert "1512 g" in pab.explain("Nozzle hit the model or bed! Weight 1512 > 1500; Extruder Off!")
    assert pab.explain("MCU 'mcu' shutdown: Timer too close\nmore") == "ZMod Klipper says: MCU 'mcu' shutdown: Timer too close"
    assert "didn't say why" in pab.explain("")


def test_components_shutdown_has_no_resume(tmp_path):
    assert [b["label"] for b in pab.components("a", "shutdown")[0]["components"]] == ["Cancel print"]
    assert [b["label"] for b in pab.components("a", "paused")[0]["components"]] == ["Resume print", "Cancel print"]
    assert [b["label"] for b in pab.components("a", "visual")[0]["components"]] == ["Pause", "It's fine"]


def test_visual_button_ids_parse():
    assert pab.parse_custom_id("pbalert:pause:ab12") == ("pause", "ab12")
    assert pab.parse_custom_id("pbalert:acknowledge:ab12") == ("acknowledge", "ab12")


def test_post_visual_alert_uses_one_multipart_message_with_components(tmp_path, monkeypatch):
    image = tmp_path / "camera.jpg"
    image.write_bytes(b"jpeg-data")
    seen = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_open(request, timeout):
        seen["request"], seen["timeout"] = request, timeout
        return Response()

    with patch.object(pab, "STATE", tmp_path / "alerts.json"), patch.object(pab.urllib.request, "urlopen", fake_open):
        assert pab.post_visual_alert("token", "channel", "Camera check", "f.gcode", image)
    request = seen["request"]
    assert seen["timeout"] == 20
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'"label": "Pause"' in request.data and b"\"label\": \"It's fine\"" in request.data
    assert b"jpeg-data" in request.data


def test_record_take_once(tmp_path):
    with patch.object(pab, "STATE", tmp_path / "s.json"):
        aid = pab.record("paused", "f.gcode")
        assert pab.take(aid)["filename"] == "f.gcode"
        assert pab.take(aid) is None
        assert "already answered" in pab.handle_click("cancel", None)


def test_parse_custom_id():
    assert pab.parse_custom_id("pbalert:cancel:ab12") == ("cancel", "ab12")
    assert pab.parse_custom_id("clarify:x:y") is None
    assert pab.parse_custom_id("pbalert:explode:ab") is None


def test_insertion_components_and_parse_are_button_only():
    components = pab.insertion_components("deadbeef")
    assert [button["label"] for button in components[0]["components"]] == ["Same spool", "Existing spool", "New spool"]
    assert pab.parse_insertion_custom_id("pbinsert:new:deadbeef") == ("new", "deadbeef")
    assert pab.parse_insertion_custom_id("pbinsert:bad:deadbeef") is None


def test_spool_question_buttons_hide_same_without_prior_and_parse():
    assert [button["label"] for button in pab.spool_question_components("deadbeef")[0]["components"]] == ["Existing spool", "New spool"]
    assert [button["label"] for button in pab.spool_question_components("deadbeef", 8)[0]["components"]] == ["Same spool", "Existing spool", "New spool"]
    assert pab.parse_spool_question_custom_id("pbspool:new:deadbeef") == ("new", "deadbeef")
    assert pab.parse_spool_question_custom_id("pbspool:bad:deadbeef") is None


def test_insertion_select_orders_closest_material_and_color_first():
    options = pab.insertion_select_options([
        {"id": 3, "filament": {"material": "PLA", "name": "Black"}},
        {"id": 4, "filament": {"material": "PLA+", "name": "Pink"}},
        {"id": 5, "filament": {"material": "PLA+", "name": "Black"}},
    ], {"material": "PLA+", "color": "black"}, {4})
    assert [option["value"] for option in options] == ["5", "3"]


def test_new_insertion_fixture_preserves_lot_and_never_pushes_printer_screen():
    calls = []

    class Sync:
        @staticmethod
        def parse_new(text):
            assert text == ", PLA+, Black, 1000"
            return {"material": "PLA+", "color": "Black", "grams": 1000}

        @staticmethod
        def create_spool(spec):
            calls.append(("create", spec))
            return {"spool_id": 31}

        @staticmethod
        def bind_slot(slot, spool_id, **kwargs):
            calls.append(("bind", slot, spool_id, kwargs))
            return {"record": {"name": "Black PLA+"}}

    out = pab.create_and_bind_insertion(3, {"brand": "", "material": "PLA+", "color": "Black",
                                            "grams": "1000", "lot": "XHXf1821-ty-21"}, Sync)
    assert "#31" in out and "printer untouched" in out
    assert calls[0][1]["lot"] == "XHXf1821-ty-21"
    assert calls[1][3]["push_screen_update"] is False


def test_visual_acknowledgement_never_contacts_printer():
    assert pab.handle_click("acknowledge", {"kind": "visual", "filename": "f.gcode"}) == (
        "Visual check acknowledged. Monitoring continues; nothing sent to the printer.")


def test_visual_pause_requires_current_matching_print():
    with patch("print_buddy.hermes.print_control.status", return_value={"klippy": "ready", "state": "printing", "filename": "other.gcode"}), \
         patch("print_buddy.hermes.print_control._call") as call:
        out = pab.handle_click("pause", {"kind": "visual", "filename": "f.gcode"})
    call.assert_not_called()
    assert "different print" in out

    with patch("print_buddy.hermes.print_control.status", return_value={"klippy": "ready", "state": "printing", "filename": "f.gcode"}), \
         patch("print_buddy.hermes.print_control._call") as call:
        assert pab.handle_click("pause", {"kind": "visual", "filename": "f.gcode"}).startswith("Pause sent.")
    call.assert_called_once_with("/printer/print/pause", method="POST", timeout=15)


def test_cancel_after_shutdown_clears_then_finds_job_gone():
    seq = iter([{"klippy": "shutdown", "state": "paused", "filename": "f.gcode"},
                {"klippy": "ready", "state": "standby", "filename": ""}])
    with patch("print_buddy.hermes.print_control.status", side_effect=lambda: next(seq)), \
         patch.object(pab, "clear_shutdown", return_value=(True, "Cleared.")) as clr, \
         patch("print_buddy.hermes.print_stop.cancel") as cancel:
        out = pab.handle_click("cancel", {"filename": "f.gcode"})
    clr.assert_called_once(); cancel.assert_not_called()
    assert "Cleared." in out and "already gone" in out


def test_cancel_paused_ready_cancels_same_file_only():
    st = {"klippy": "ready", "state": "paused", "filename": "other.gcode"}
    with patch("print_buddy.hermes.print_control.status", return_value=st), patch("print_buddy.hermes.print_stop.cancel") as cancel:
        out = pab.handle_click("cancel", {"filename": "f.gcode"})
    cancel.assert_not_called(); assert "different print" in out
    st["filename"] = "f.gcode"
    with patch("print_buddy.hermes.print_control.status", return_value=st), patch("print_buddy.hermes.print_stop.cancel", return_value=(True, "Stopped.")) as cancel:
        assert pab.handle_click("cancel", {"filename": "f.gcode"}) == "Stopped."
    cancel.assert_called_once_with("f.gcode")


def test_resume_after_shutdown_refuses_without_restart():
    with patch("print_buddy.hermes.print_control.status", return_value={"klippy": "shutdown", "state": "paused", "filename": "f"}), \
         patch("print_buddy.hermes.print_control._call") as call, patch.object(pab, "clear_shutdown") as clr:
        out = pab.handle_click("resume", {"filename": "f"})
    call.assert_not_called(); clr.assert_not_called()
    assert "Nothing sent" in out


def test_clear_shutdown_reports_timeout_without_retry():
    calls = []
    ok, msg = pab.clear_shutdown(wait_s=0.05, poll_s=0.01, caller=lambda *a, **k: calls.append(a),
                                 reader=lambda: {"klippy": "shutdown"})
    assert not ok and len(calls) == 1 and "Not retrying" in msg


def test_clear_shutdown_uses_non_klipper_profile_firmware_name(monkeypatch):
    from print_buddy import printers, settings

    config = settings.load(home=settings.HOME, local=False,
                           environ={"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"})
    profile = printers.current(config)
    monkeypatch.setattr(printers, "current", lambda: profile)
    ok, message = pab.clear_shutdown(wait_s=0.05, poll_s=0.001, caller=lambda *a, **k: None,
                                     reader=lambda: {"klippy": "ready"})

    assert ok
    assert "Bambu Lab (offline handoff only)" in message
    assert "Klipper" not in message


def test_listener_shutdown_text_has_reason():
    text = mel.shutdown_alert_text("Hello-Kitty_plate_1_" + "ab" * 32 + ".gcode", LIVE)
    assert "**Why:**" in text and "1512 g" in text and "Cancel print" in text


def test_listener_falls_back_to_plain_post():
    with patch.object(pab, "post_with_buttons", return_value=False), patch.object(mel, "post", return_value=True) as p:
        assert mel.post_alert("hi", "paused", "f") is True
    p.assert_called_once_with("hi")
