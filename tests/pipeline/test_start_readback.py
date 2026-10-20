"""Unit tests for classify_start_readback and start readback integration (Issue #84)."""
import pytest
from print_buddy.core.model_job import classify_start_readback, StartReadback


def test_classify_failed_error():
    snap = {"print_stats": {"state": "error"}}
    rb = classify_start_readback(snap)
    assert isinstance(rb, StartReadback)
    assert rb.outcome == "failed"
    assert "state" in rb.evidence
    assert "failed" in rb.message


def test_classify_failed_cancelled():
    snap = {"result": {"status": {"print_stats": {"state": "cancelled"}}}}
    rb = classify_start_readback(snap)
    assert rb.outcome == "failed"
    assert rb.evidence["state"] == "cancelled"


def test_classify_failed_webhooks_shutdown():
    snap = {"webhooks": {"state": "shutdown"}}
    rb = classify_start_readback(snap)
    assert rb.outcome == "failed"
    assert rb.evidence["state"] == "shutdown"


def test_classify_printing_with_filament_used():
    snap = {
        "print_stats": {
            "state": "printing",
            "filament_used": 12.5,
            "info": {"current_layer": 2, "total_layer": 100},
        }
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "printing"
    assert rb.message == "printing"
    assert rb.evidence["filament_used"] == 12.5
    assert rb.evidence["extrusion_confirmed"] is True


def test_classify_printing_with_extruder_delta():
    snap = {
        "print_stats": {"state": "printing", "filament_used": 0.0},
        "extruder_position_delta": 1.5,
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "printing"
    assert rb.message == "printing"
    assert rb.evidence["extrusion_confirmed"] is True


def test_classify_printing_zero_extrusion_layer_1():
    """NEW evidence from tonight: layer 1 reported while still heating/purging.
    filament_used is 0, so extrusion is not confirmed."""
    snap = {
        "print_stats": {
            "state": "printing",
            "filament_used": 0.0,
            "info": {"current_layer": 1, "total_layer": 141},
        }
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "printing"
    assert rb.message == "printing (extrusion not yet confirmed)"
    assert rb.evidence["extrusion_confirmed"] is False
    assert rb.evidence["filament_used"] == 0.0


def test_classify_printing_no_extrusion_keys():
    snap = {
        "print_stats": {
            "state": "printing",
        }
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "printing"
    assert rb.message == "printing (extrusion not yet confirmed)"
    assert rb.evidence["extrusion_confirmed"] is False


def test_classify_preparing_heating_extruder():
    snap = {
        "extruder": {"target": 210.0},
        "heater_bed": {"target": 0.0},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert "heating" in rb.evidence
    assert rb.evidence["heating"]["extruder"] == 210.0
    assert "not a failure; do not resubmit" in rb.message


def test_classify_preparing_heating_bed():
    snap = {
        "extruder": {"target": 0.0},
        "heater_bed": {"target": 60.0},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert "heating" in rb.evidence
    assert rb.evidence["heating"]["heater_bed"] == 60.0


def test_classify_preparing_homing():
    snap = {
        "toolhead": {"homed_axes": "xyz"},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert rb.evidence["homing"] == "xyz"


def test_classify_preparing_virtual_sdcard():
    snap = {
        "virtual_sdcard": {"is_active": True, "file_path": "test.gcode"},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert "virtual_sdcard" in rb.evidence


def test_classify_preparing_idle_printing():
    snap = {
        "idle_timeout": {"state": "Printing"},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert rb.evidence["idle_timeout"] == "Printing"


def test_classify_preparing_ifs_loading():
    snap = {
        "zmod_ifs": {"state": "loading"},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "preparing"
    assert "zmod_ifs" in rb.evidence


def test_classify_unconfirmed_empty():
    snap = {}
    rb = classify_start_readback(snap)
    assert rb.outcome == "unconfirmed"
    assert rb.evidence is None
    assert rb.message == "submitted, awaiting confirmation"


def test_classify_unconfirmed_idle_ready():
    snap = {
        "print_stats": {"state": "standby"},
        "idle_timeout": {"state": "Ready"},
        "extruder": {"target": 0},
        "heater_bed": {"target": 0},
    }
    rb = classify_start_readback(snap)
    assert rb.outcome == "unconfirmed"
    assert rb.evidence is None
    assert rb.message == "submitted, awaiting confirmation"
