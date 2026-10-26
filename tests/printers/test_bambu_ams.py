"""Bambu Lab AMS read (#307; Stage 2a of #298): offline tests only — fake MQTT, never a socket.

Payloads follow the recorded wire shapes (pybambu's documented payload in
docs/BAMBU-CONNECTIVITY.md; the #298 Stage 0 audit rows 3–5): an `ams` block of units
with trays, `tray_exist_bits` as the presence authority, `humidity_raw` as the only
humidity percentage, `tray_now` naming the active tray, `vt_tray` for the external
spool, and bit 18 of the `cfg` hex string as Filament Backup (captured values below).
Decoding is read-only: nothing in this stage publishes a command beyond the snapshot's
own get_version + pushall, and the print-start payload is pinned byte-identical.
"""
import copy

from print_buddy import printers
from print_buddy.core import printer_state
from print_buddy.printers.bambulab import ams
from print_buddy.printers.bambulab.client import BambuLanClient, project_file_payload

from .test_bambu_lan import CODE, SERIAL, FakeMqtt, config_for, factory_for, lan_adapter

# One regular AMS unit, all four trays reported. tray_exist_bits "5" (0b0101) says
# trays 0 and 2 hold spools. Tray 1 deliberately carries full metadata AND a `state`
# value: presence must still be False, because the bits — never the firmware-variant
# `state` field, never the metadata — are the authority when they are reported.
FULL_PRINT = {
    "command": "push_status", "msg": 0, "gcode_state": "IDLE", "mc_percent": 0,
    "cfg": "C0340FC219",  # captured with Filament Backup ON (bit 18 set)
    "ams": {
        "ams": [{"id": "0", "humidity": "4", "humidity_raw": "41", "temp": "24.5",
                 "tray": [
                     {"id": "0", "state": 8, "tray_type": "PLA", "tray_sub_brands": "Bambu PLA Basic",
                      "tray_info_idx": "GFL99", "tray_color": "FF0000FF", "remain": 87},
                     {"id": "1", "state": 1, "tray_type": "PETG", "tray_sub_brands": "Bambu PETG Basic",
                      "tray_info_idx": "GFG99", "tray_color": "00FF00FF", "remain": 50},
                     {"id": "2", "state": 8, "tray_type": "PLA", "tray_sub_brands": "",
                      "tray_info_idx": "GFL99", "tray_color": "0000FFFF", "remain": -1},
                     {"id": "3", "state": 0, "tray_type": "", "tray_sub_brands": "",
                      "tray_info_idx": "", "tray_color": "00000000", "remain": -1},
                 ]}],
        "ams_exist_bits": "1", "tray_exist_bits": "5", "tray_is_bbl_bits": "5",
        "tray_now": "2", "tray_tar": "2", "version": 3},
    "vt_tray": {"id": "254", "tray_type": "TPU", "tray_sub_brands": "", "tray_info_idx": "GFU99",
                "tray_color": "FFFFFFFF", "remain": 100},
}

VERSION_AMS = {"command": "get_version",
               "module": [{"name": "ota", "sw_ver": "01.05.00.00"},
                          {"name": "ams/0", "hw_ver": "AMS08", "sn": "AMS000000000000"}]}


def _adapter():
    return printers.get("bambulab.a1", config_for())


# --------------------------------------------------------------------- decoding

def test_full_report_decodes_trays_external_spool_and_backup():
    out = ams.decode_ams(copy.deepcopy(FULL_PRINT), VERSION_AMS)
    assert out == {
        "units": [{"id": 0, "kind": "ams", "humidity_pct": 41, "temp_c": 24.5,
                   "trays": [
                       {"slot": 0, "present": True, "material": "PLA", "name": "Bambu PLA Basic",
                        "color": "FF0000", "remaining_pct": 87, "active": False},
                       {"slot": 1, "present": False, "material": "PETG", "name": "Bambu PETG Basic",
                        "color": "00FF00", "remaining_pct": 50, "active": False},
                       {"slot": 2, "present": True, "material": "PLA", "name": "",
                        "color": "0000FF", "remaining_pct": None, "active": True},
                       {"slot": 3, "present": False, "material": None, "name": "",
                        "color": None, "remaining_pct": None, "active": False},
                   ]}],
        "external": {"present": True, "material": "TPU", "name": "", "color": "FFFFFF",
                     "remaining_pct": 100, "active": False},
        "active_tray": 2,
        "filament_backup": True,
    }


def test_presence_comes_from_exist_bits_not_state_or_metadata():
    payload = {"ams": {"ams": [{"id": "0", "tray": [
        {"id": "0", "state": 1, "tray_type": "PLA", "tray_info_idx": "GFL99"},   # metadata + state, bit clear
        {"id": "1", "state": 0, "tray_type": "", "tray_info_idx": ""},          # nothing at all, bit set
    ]}], "tray_exist_bits": "2", "tray_now": "255"}}
    trays = ams.decode_ams(payload)["units"][0]["trays"]
    assert [t["present"] for t in trays] == [False, True]


def test_presence_falls_back_to_metadata_only_when_bits_are_absent():
    payload = {"ams": {"ams": [{"id": "0", "tray": [
        {"id": "0", "tray_type": "PLA", "tray_info_idx": ""},
        {"id": "1", "tray_type": "", "tray_info_idx": "GFL99"},
        {"id": "2", "tray_type": "", "tray_info_idx": ""},
    ]}], "tray_now": "255"}}
    trays = ams.decode_ams(payload)["units"][0]["trays"]
    assert [t["present"] for t in trays] == [True, True, False]


def test_humidity_uses_the_raw_percentage_never_the_index():
    def humidity(unit):
        payload = {"ams": {"ams": [dict(unit, id="0", tray=[])], "tray_now": "255"}}
        return ams.decode_ams(payload)["units"][0]["humidity_pct"]

    assert humidity({"humidity": "4", "humidity_raw": "41"}) == 41
    assert humidity({"humidity": "5"}) is None        # the 1–5 index alone is not a percentage
    assert humidity({"humidity": "1", "humidity_raw": "0"}) is None   # out-of-range raw is bogus, index not a fallback
    assert humidity({"humidity_raw": "100"}) == 100


def test_filament_backup_is_bit_18_of_cfg_and_unknown_when_absent():
    def backup(payload):
        return ams.decode_ams({**payload, "vt_tray": {}})["filament_backup"]

    assert backup({"cfg": "C0340FC219"}) is True    # captured, backup ON
    assert backup({"cfg": "C0340BC219"}) is False   # same printer, backup OFF — only bit 18 flips
    assert backup({"cfg": "FCA09"}) is True         # captured short X1C form
    assert backup({"cfg": "c0340fc219"}) is True    # lower-case hex parses the same
    assert backup({}) is None                       # old-protocol A1 family sends no cfg: unknown, never off
    assert backup({"cfg": ""}) is None
    assert backup({"cfg": "not_hex"}) is None
    assert backup({"cfg": 123}) is None


def test_active_tray_encodings():
    def decode(now, **block_kw):
        block = {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PLA"},
                                              {"id": "1", "tray_type": "PLA"}]}],
                 "tray_exist_bits": "3", **block_kw}
        if now is not None:
            block["tray_now"] = now
        return ams.decode_ams({"ams": block, "vt_tray": {"tray_type": "PLA", "tray_info_idx": "GFL99"}})

    out = decode("1")
    assert out["active_tray"] == 1 and out["units"][0]["trays"][1]["active"] is True
    assert out["external"]["active"] is False

    out = decode("254")  # the external spool is active
    assert out["active_tray"] == 254 and out["external"]["active"] is True
    assert not any(t["active"] for t in out["units"][0]["trays"])

    out = decode("255")  # nothing active
    assert out["active_tray"] is None and out["external"]["active"] is False

    out = decode(None)   # no tray_now reported at all
    assert out["active_tray"] is None

    out = decode("99")   # outside every recorded encoding: nothing is marked active
    assert out["active_tray"] is None
    assert not any(t["active"] for t in out["units"][0]["trays"])


def test_ams_ht_unit_reports_its_unit_id_as_the_active_tray():
    payload = {"ams": {"ams": [{"id": "128", "tray": [{"id": "0", "tray_type": "PA",
                                                       "tray_info_idx": "GFN99"}]}],
                       "tray_now": "128"}}
    info = {"module": [{"name": "n3s/0", "hw_ver": "AMS_HT"}]}
    out = ams.decode_ams(payload, info)
    unit = out["units"][0]
    assert unit["kind"] == "ams_ht" and unit["trays"][0]["present"] is True
    assert unit["trays"][0]["active"] is True and out["active_tray"] == 128


def test_unit_kinds_come_from_the_hardware_report_not_the_model():
    def kind(module_name, unit_id="0"):
        payload = {"ams": {"ams": [{"id": unit_id, "tray": []}], "tray_now": "255"}}
        info = {"module": [{"name": module_name}]}
        return ams.decode_ams(payload, info)["units"][0]["kind"]

    assert kind("ams/0") == "ams"
    assert kind("ams_f1/0") == "ams_lite"
    assert kind("n3f/0") == "ams_2_pro"
    assert kind("n3s/0", "128") == "ams_ht"
    payload = {"ams": {"ams": [{"id": "0", "tray": []}], "tray_now": "255"}}
    assert ams.decode_ams(payload)["units"][0]["kind"] is None        # no version info: no guess
    assert ams.decode_ams(payload, {"module": []})["units"][0]["kind"] is None


def test_no_ams_report_decodes_to_none_and_vt_tray_alone_decodes():
    assert ams.decode_ams({"gcode_state": "IDLE"}) is None
    assert ams.decode_ams({}) is None
    assert ams.decode_ams(None) is None
    out = ams.decode_ams({"vt_tray": {"tray_type": "", "tray_info_idx": ""}})
    assert out["units"] == [] and out["external"]["present"] is False
    assert out["active_tray"] is None and out["filament_backup"] is None


# --------------------------------------------------------------------- adapter + snapshot

def test_normalize_status_carries_the_decoded_ams_state():
    a = _adapter()  # an A1 — its facts say AMS Lite…
    snap = {"print": copy.deepcopy(FULL_PRINT), "info": copy.deepcopy(VERSION_AMS), "online": True}
    out = a.normalize_status(snap)
    # …but the snapshot's own version report says a regular AMS is attached, and the
    # hardware report — never the model name — is what the decoder believes.
    assert out["ams"]["units"][0]["kind"] == "ams"
    assert out["ams"]["active_tray"] == 2 and out["ams"]["filament_backup"] is True
    assert a.normalize_status({"print": {"gcode_state": "IDLE"}})["ams"] is None
    assert a.normalize_status({"print_stats": {"state": "printing"}})["ams"] is None  # Moonraker shape


def test_snapshot_merges_partial_ams_frames_before_decoding():
    delta = {"print": {"command": "push_status", "msg": 1, **copy.deepcopy(FULL_PRINT)}}
    delta["print"]["ams"]["tray_now"] = "0"
    partial = {"print": {"command": "push_status", "msg": 1, "ams": {"tray_now": "2"}}}
    version = {"info": copy.deepcopy(VERSION_AMS)}
    final = {"print": {"command": "push_status", "msg": 0, "gcode_state": "IDLE"}}
    fake = FakeMqtt(script=[delta, partial, version, final])
    client = BambuLanClient("192.168.1.50", SERIAL, CODE, mqtt_factory=factory_for(fake))
    snap = client.snapshot()
    # Read-only: the snapshot published exactly its two requests and nothing else.
    published = [payload for _topic, payload in fake.published]
    assert [next(iter(p.values()))["command"] for p in published] == ["get_version", "pushall"]
    out = _adapter().normalize_status(snap)
    trays = out["ams"]["units"][0]["trays"]
    assert len(trays) == 4 and trays[0]["material"] == "PLA"  # the partial frame dropped nothing
    assert out["ams"]["active_tray"] == 2 and trays[2]["active"] is True  # …and its update landed


def test_project_file_payload_is_unchanged_by_ams_read():
    # The print-start payload is pinned literally: AMS read must not move a byte of it
    # (real mapping is #308, behind its own gates).
    assert project_file_payload("job.gcode.3mf") == {
        "print": {"sequence_id": "0", "command": "project_file", "param": "Metadata/plate_1.gcode",
                  "file": "job.gcode.3mf", "url": "ftp:///job.gcode.3mf", "bed_type": "auto",
                  "timelapse": False, "bed_leveling": False, "flow_cali": False,
                  "vibration_cali": False, "layer_inspect": False, "use_ams": False,
                  "ams_mapping": [0], "subtask_name": "job.gcode.3mf", "profile_id": "0",
                  "project_id": "0", "subtask_id": "0", "task_id": "0"}}


# --------------------------------------------------------------------- printer_state surfacing

def _check_with_snapshot(monkeypatch, snap, record):
    a = lan_adapter(monkeypatch)
    monkeypatch.setattr(a, "client", lambda **kw: type("C", (), {"snapshot": lambda self: snap})())
    monkeypatch.setattr(printers, "current", lambda config=None: a)
    monkeypatch.setattr(printer_state, "_get",
                        lambda url, data=None, method=None, timeout=6:
                        {"id": 10, "archived": False,
                         "filament": {"name": "recorded", "material": record["spool"].get("material")},
                         "remaining_weight": 900})
    return printer_state.check(record)


def _record(**spool):
    return {"bed_mm": [256, 256], "max_print_height_mm": 256,
            "nozzle": {"diameter_mm": 0.4, "type": "stainless_steel"},
            "spool": {"spoolman_id": 10, "name": "recorded", **spool},
            "spoolman_url": "http://spoolman.test:7912"}


def _snap_with_active(material, color, now="1"):
    payload = copy.deepcopy(FULL_PRINT)
    payload["ams"]["tray_exist_bits"] = "3"
    payload["ams"]["tray_now"] = now
    tray = payload["ams"]["ams"][0]["tray"][int(now)]
    tray["tray_type"], tray["tray_color"] = material, color
    return {"print": payload, "info": copy.deepcopy(VERSION_AMS), "online": True}


def test_check_warns_when_the_active_tray_disagrees_with_the_record(monkeypatch):
    snap = _snap_with_active("PETG", "00FF00FF")  # active tray 1: PETG, green
    ok, probs, facts = _check_with_snapshot(monkeypatch, snap, _record(material="PLA", color="00FF00"))
    assert (ok, probs) == (True, [])  # advisory only — never a readiness problem
    ams_warnings = [w for w in facts["warnings"] if "active Bambu tray" in w]
    assert len(ams_warnings) == 1 and "PETG" in ams_warnings[0] and "PLA" in ams_warnings[0]


def test_check_warns_on_hex_colour_disagreement_only(monkeypatch):
    snap = _snap_with_active("PETG", "00FF00FF")
    ok, probs, facts = _check_with_snapshot(monkeypatch, snap, _record(material="PETG", color="#FF0000"))
    assert (ok, probs) == (True, [])
    ams_warnings = [w for w in facts["warnings"] if "active Bambu tray" in w]
    assert len(ams_warnings) == 1 and "00FF00" in ams_warnings[0] and "FF0000" in ams_warnings[0]


def test_check_is_quiet_when_the_active_tray_agrees_with_the_record(monkeypatch):
    snap = _snap_with_active("PETG", "00FF00FF")
    # The record's colour is a name, not hex: it must not be compared against the
    # printer's hex (that pairing would warn on every single check).
    ok, probs, facts = _check_with_snapshot(monkeypatch, snap, _record(material="PETG", color="green"))
    assert (ok, probs) == (True, [])
    assert not [w for w in facts["warnings"] if "active Bambu tray" in w]
    assert facts["bambu"]["ams"]["active_tray"] == 1  # the decoded state itself is surfaced
