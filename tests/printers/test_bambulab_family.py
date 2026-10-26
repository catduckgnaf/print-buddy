"""Bambu Lab #127 Stage 1 models: A1 mini, P1P, X1, X1 Carbon, X1E, P2S, H2S.

Every model shares the bambulab vendor and LAN client; what is per-model is its facts,
its pinned OrcaSlicer identity, and its MODEL. These tests pin all three offline: the
recorded identities are the real OrcaSlicer 2.4.2 hashes (computed with profiles.flatten
over the pinned release; the pipeline reproduces A1/P1S exactly), while profile install
and the guard are exercised against invented fixture resources, as for the P1S.
"""
import json
import re
from pathlib import Path

import pytest

from print_buddy import printers, settings
from print_buddy.printers.bambulab import VENDOR, facts, profiles
from print_buddy.printers.bambulab.adapter import BambuAdapter
from print_buddy.printers.bambulab.client import BambuLanError
from print_buddy.printers.bambulab.guard import ForeignStartCode

from . import bambu_family_fixture as fixture

ROOT = Path(__file__).resolve().parents[2]

# key -> (facts dict name, templates folder)
MODELS = {
    "bambulab.a1mini": ("A1MINI", "bambulab_a1mini"),
    "bambulab.p1p": ("P1P", "bambulab_p1p"),
    "bambulab.x1": ("X1", "bambulab_x1"),
    "bambulab.x1c": ("X1C", "bambulab_x1c"),
    "bambulab.x1e": ("X1E", "bambulab_x1e"),
    "bambulab.p2s": ("P2S", "bambulab_p2s"),
    "bambulab.h2s": ("H2S", "bambulab_h2s"),
}


def model_facts(key):
    return getattr(facts, MODELS[key][0])


def config_for(key, hermes=fixture.HERMES, **printer):
    env = {"PRINT_BUDDY__PRINTER__MODEL": key, "PRINT_BUDDY__PATHS__HERMES_HOME": str(hermes),
           **{f"PRINT_BUDDY__PRINTER__{k.upper()}": str(v) for k, v in printer.items()}}
    return settings.load(local=False, environ=env)


def adapter_for(key, cfg=None):
    return printers.get(key, cfg or config_for(key))


@pytest.mark.parametrize("key", sorted(MODELS))
def test_model_registration_and_defaults(key):
    model = printers.MODELS[key]
    assert model.vendor is VENDOR is printers.VENDORS["bambulab"]
    assert model.templates == MODELS[key][1] and model.generated_templates is True
    assert model.baseline == f"protected-settings-baseline.{key}.json"
    a = adapter_for(key)
    assert isinstance(a, BambuAdapter)
    assert (a.connection, a.slot_count, a.multi_slot) == ("bambulab_lan", 1, False)
    f = model_facts(key)
    volume = a.build_volume()
    assert volume.bed_mm == tuple(float(v) for v in f["bed_mm"].value)
    assert volume.max_height_mm == float(f["max_print_height_mm"].value)
    assert a.supported_nozzle_sizes == (0.4,)
    assert set(a.supported_nozzle_types) == {"stainless_steel", "hardened_steel"}
    cfg = config_for(key)
    assert cfg["printer"]["model"] == key and cfg["printer"]["slicer"] == "bambu_studio"
    assert cfg["printer"]["bed_mm"] == [float(v) for v in f["bed_mm"].value]
    assert cfg["printer"]["nozzle_type"] == f["stock_nozzle"].value[1]
    with pytest.raises(settings.SettingsError, match="not supported by model"):
        config_for(key, nozzle_diameter_mm=0.6)


@pytest.mark.parametrize("key", sorted(MODELS))
def test_recorded_identity_is_a_real_pin(key):
    f = model_facts(key)
    (known,) = f["orca_identity"].value
    assert known["vendor_version"] == "02.01.00.19"
    assert set(known["sha256"]) == {"machine", "process", "filament"}
    for digest in known["sha256"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
    names = f["orca_profiles"].value
    assert names["machine"] == f"{f['printer_model'].value} 0.4 nozzle"
    # The invented fixture must NOT match the recorded identity: install refuses it
    # until a test swaps the identity in, which proves the pin is checked.
    assert fixture.identity(f)["sha256"] != known["sha256"]


@pytest.mark.parametrize("key", sorted(MODELS))
def test_fixture_profile_install_and_guard(key, monkeypatch):
    f = model_facts(key)
    a = adapter_for(key)
    fixture.trust(type(a), f, monkeypatch.setattr)
    folder = fixture.install(a, f)
    assert profiles.problems(a) == []
    machine = json.loads((folder / "machine.json").read_text())
    assert machine["printer_model"] == f["printer_model"].value
    # The adapter accepts exactly the vendor start block from the verified templates...
    start = a.machine_start_gcode(machine["machine_start_gcode"])
    assert start == machine["machine_start_gcode"]
    # ...and refuses Klipper/ZMod start code for this printer.
    with pytest.raises(ForeignStartCode):
        a.machine_start_gcode("PRINT_START BED=60\n")


@pytest.mark.parametrize("key", sorted(MODELS))
def test_motion_envelope_covers_bed_and_vendor_moves(key):
    f = model_facts(key)
    xmin, ymin, xmax, ymax = f["motion_envelope_mm"].value
    (w, d) = f["bed_mm"].value
    # The envelope must at least cover the whole bed: toolpath moves are held to it.
    assert xmin <= 0 and ymin <= 0 and xmax >= w and ymax >= d


@pytest.mark.parametrize("key", sorted(MODELS))
def test_lan_unconfigured_by_default_and_status_normalizes(key):
    a = adapter_for(key)
    assert a.lan_configured() is False
    with pytest.raises(BambuLanError, match="LAN telemetry is not configured"):
        a.client()
    snapshot = {"print": {"gcode_state": "RUNNING", "mc_percent": 42, "nozzle_temper": 210.0,
                          "bed_temper": 60.0, "subtask_name": "benchy.gcode.3mf"}}
    out = a.normalize_status(snapshot)
    assert out["state"] == "printing" and out["progress"] == 0.42
    assert out["hotend_c"] == 210.0 and out["bed_c"] == 60.0
    assert a.normalize_status({})["state"] == "unknown"


def test_model_set_is_stage1_plus_the_registered_dual_nozzle_models():
    bambu = {k for k in printers.MODELS if k.startswith("bambulab.")}
    assert bambu == {"bambulab.a1", "bambulab.p1s"} | set(MODELS) | {"bambulab.h2d", "bambulab.h2dpro",
                                                                     "bambulab.x2d"}
    # H2C and A2L stay absent (#308): neither has a profile in the pinned OrcaSlicer
    # 2.4.2 BBL index, so no checked identity can be established for them.
    assert not ({"bambulab.h2c", "bambulab.a2l"} & bambu)
