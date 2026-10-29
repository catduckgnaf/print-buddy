"""#620: the progress control lists both objects and sends one name only after confirm."""
from pathlib import Path

from print_handy.core.exclude_object import exclude_plan
from print_handy.hermes.exclude_chat import (
    components, confirm_send, parse_custom_id, prepare, surface_text,
)


def test_two_objects_render_and_a_file_with_no_metadata_does_not():
    names = ["hinge_left", "hinge_right"]
    text = surface_text(names)
    assert "hinge_left" in text and "hinge_right" in text
    options = components("abc", names)[0]["components"][0]["options"]
    assert [row["label"] for row in options] == ["Cancel hinge_left", "Cancel hinge_right"]
    assert options[0]["value"] == "0"
    assert parse_custom_id("pbexclude:pick:abc") == ("pick", "abc")
    assert surface_text([]) == ""
    assert components("abc", []) == []
    assert parse_custom_id("pbplate:go:abc") is None


def test_choose_asks_and_confirm_sends_only_that_name():
    alert = {"kind": "exclude-pick", "filename": "plate.gcode", "names": ["hinge_left", "hinge_right"]}
    asked = prepare(alert, 0)
    assert asked["step"] == "confirm" and asked["name"] == "hinge_left"
    unconfirmed = exclude_plan(alert["names"], "hinge_left", confirmed=False)
    assert unconfirmed["body"] is None
    sent_to = []

    def sender(script):
        sent_to.append(script)

    gone = confirm_send({"kind": "exclude-go", "name": "hinge_left", "names": alert["names"]}, sender)
    assert gone["sent"] is True
    assert sent_to == ["EXCLUDE_OBJECT NAME=hinge_left"]
    assert "hinge_right" not in sent_to[0]


def test_last_object_is_the_stop_confirm_and_a_failed_send_is_not_cancelled():
    last = prepare({"kind": "exclude-pick", "names": ["only"], "filename": "plate.gcode"}, 0)
    assert last["step"] == "cancel_print"
    sent_to = []
    refused = confirm_send({"kind": "exclude-go", "name": "only", "names": ["only"]},
                           lambda script: sent_to.append(script))
    assert refused["sent"] is False and sent_to == []
    assert "excluded" in refused["text"].lower() or "Nothing" in refused["text"]

    def boom(script):
        raise OSError("refused")

    failed = confirm_send({"kind": "exclude-go", "name": "hinge_left",
                           "names": ["hinge_left", "hinge_right"]}, boom)
    assert failed["sent"] is False
    assert "not cancelled" in failed["text"]
    assert "Exclude sent" not in failed["text"]


def test_watchdog_check_does_not_exclude_or_stop():
    path = Path(__file__).resolve().parents[2] / "print_handy/hermes/moonraker_event_listener.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("    async def visual_check")
    end = text.index("    async def on_status", start)
    body = text[start:end]
    assert "exclude_object" not in body
    assert "EXCLUDE_OBJECT" not in body
    assert "print/cancel" not in body
    assert "print_stop" not in body
