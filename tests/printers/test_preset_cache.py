"""OrcaSlicer 2.5+ packed preset caches (<Vendor>.opc): the preset_cache reader and its
profiles.py integration, exercised against a small cache built byte-by-byte here in the
format OrcaSlicer writes (PresetCacheFormat, format version 2). No Orca profile content:
every preset below is invented, and the real caches' identities are pinned in facts.py.
"""
import math
import struct
import zlib

import pytest

from print_handy.printers.bambulab import preset_cache, profiles

# ConfigOptionType values used below (see preset_cache).
FLOAT, INT, STRING, PERCENT, FLOAT_OR_PERCENT, BOOL, ENUM = 1, 2, 3, 4, 5, 8, 9
VEC = 0x4000
FLOATS, PERCENTS, POINTS, ENUMS = FLOAT + VEC, PERCENT + VEC, 6 + VEC, ENUM + VEC

KEYS = [("layer_height", FLOAT), ("wall_loops", INT), ("machine_start_gcode", STRING),
        ("enable_arc_fitting", BOOL), ("sparse_infill_density", PERCENT),
        ("sparse_infill_pattern", ENUM), ("filament_z_hop_types", ENUMS),
        ("retract_before_wipe", PERCENTS), ("printable_area", POINTS),
        ("line_width", FLOAT_OR_PERCENT), ("nozzle_diameter", FLOATS)]
ENUMS_TABLE = ["", "grid", "gyroid", "Normal Lift"]


def _s(text):
    data = text.encode()
    return struct.pack("<Q", len(data)) + data


def _vec(items, pack_one):
    return struct.pack("<Q", len(items)) + b"".join(pack_one(i) for i in items)


def _value(option_type, value):
    if option_type in (FLOAT, PERCENT):
        return struct.pack("<d", value)
    if option_type == INT:
        return struct.pack("<i", value)
    if option_type == STRING:
        return _s(value)
    if option_type == BOOL:
        return struct.pack("<B", 1 if value else 0)
    if option_type == FLOAT_OR_PERCENT:
        number, percent = value
        return struct.pack("<dB", number, 1 if percent else 0)
    if option_type == POINTS:
        return _vec(value, lambda p: struct.pack("<dd", *p))
    if option_type == FLOATS:
        return _vec(value, lambda v: struct.pack("<d", v))
    if option_type == PERCENTS:
        return _vec(value, lambda v: struct.pack("<d", v))
    if option_type in (ENUM, ENUMS):
        values = value if isinstance(value, list) else [value]
        out = struct.pack("<I", len(values))
        for item in values:
            if item is None:  # the unnamed-enum slot: the raw int32 follows
                out += struct.pack("<Hi", 0, 2147483647)
            else:
                out += struct.pack("<H", ENUMS_TABLE.index(item))
        return out
    raise AssertionError(option_type)


def _config(pairs):
    out = struct.pack("<I", len(pairs))
    for key, value in pairs:
        index = [k for k, _ in KEYS].index(key)
        out += struct.pack("<H", index) + _value(dict(KEYS)[key], value)
    return out


def _entry(name, pairs, inherits="", includes=(), instantiation="true"):
    return (_s(name) + _s(f"filament/{name}.json") + _config(pairs) + _s(inherits) +
            _vec(includes, _s) + _s("") + _s(instantiation) + _s("") + _s("") + _vec((), _s))


def build_cache(vendor="BBL", stamp="2.8.0.15", version=2):
    body = struct.pack("<I", version) + _s(vendor) + _s(stamp)
    body += _vec([k for k, _ in KEYS], _s)
    body += _vec([t for _, t in KEYS], lambda t: struct.pack("<H", t))
    body += _vec(ENUMS_TABLE, _s)
    # The vendor profile map: one profile with one model; the reader walks it in step.
    model = (_s("T1") + _s("Test") + _s("") + struct.pack("<B", 0) + _s("") +
             _vec(["0.4 nozzle"], _s) + _vec(["PLA"], _s) + _vec((), _s) + _s("") * 9)
    profile = (_s(vendor) + _s(vendor) + _s("2.8.0") + _s("") + _s("") +
               _vec([model], lambda m: m) + _vec(["Test Filament"], _s) + _vec((), _s))
    body += _vec([profile], lambda p: _s(vendor) + p)
    process = [
        _entry("base process", [("layer_height", 0.2), ("sparse_infill_density", 15.0),
                                ("sparse_infill_pattern", "gyroid"), ("line_width", (0.45, False))],
               instantiation="false"),
        _entry("Test Process", [("layer_height", 0.28)], inherits="base process"),
    ]
    filament = [
        _entry("Test Filament", [("filament_z_hop_types", ["Normal Lift", None]),
                                 ("retract_before_wipe", [70.0, math.nan]),
                                 ("nozzle_diameter", [0.4, 0.4])]),
    ]
    machine = [
        _entry("Test Template", [("machine_start_gcode", "G28\n")], instantiation="false"),
        _entry("Test Machine", [("printable_area", [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]),
                                ("wall_loops", 3), ("enable_arc_fitting", False)],
               includes=("Test Template",)),
    ]
    for entries in (process, filament, machine):  # the cache's own write order
        body += struct.pack("<I", len(entries)) + b"".join(entries)
    body += struct.pack("<Q", 0)  # parse errors
    header = struct.pack("<IIQI", preset_cache.MAGIC, version, len(body), zlib.crc32(body))
    return header + body


def packed_resources(tmp_path, data=None, vendor="BBL"):
    profiles_dir = tmp_path / "resources" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / f"{vendor}.opc").write_bytes(build_cache() if data is None else data)
    return tmp_path / "resources"


def load(tmp_path, data=None, vendor="BBL"):
    path = tmp_path / f"{vendor}.opc"
    path.write_bytes(build_cache(vendor=vendor) if data is None else data)
    return preset_cache.load(path, vendor)


def test_decoder_reconstructs_source_dicts(tmp_path):
    cache = load(tmp_path)
    # The stamp is unpadded; the vendor index form zero-pads each component.
    assert cache.version == "02.08.00.15"
    process = cache.sources["base process"]
    assert process == {"type": "process", "name": "base process", "from": "system",
                       "instantiation": "false", "layer_height": "0.2",
                       "sparse_infill_density": "15%", "sparse_infill_pattern": "gyroid",
                       "line_width": "0.45"}
    filament = cache.sources["Test Filament"]
    # A named enum renders as its name; the unnamed one is the option's nil.
    assert filament["filament_z_hop_types"] == ["Normal Lift", "nil"]
    # A nullable percent vector: 70% and a NaN nil.
    assert filament["retract_before_wipe"] == ["70%", "nil"]
    assert filament["nozzle_diameter"] == ["0.4", "0.4"]
    machine = cache.sources["Test Machine"]
    assert machine["printable_area"] == ["0x0", "100x0", "100x100", "0x100"]
    assert machine["wall_loops"] == "3" and machine["enable_arc_fitting"] == "0"
    assert machine["include"] == ["Test Template"]
    assert cache.sources["Test Process"]["inherits"] == "base process"


@pytest.mark.parametrize("mutate, match", [
    (lambda d: b"XXXX" + d[4:], "not an OrcaSlicer preset cache"),
    (lambda d: d[:19] + bytes([d[19] ^ 0xFF]) + d[20:], "CRC"),
    (lambda d: build_cache(version=3), "format version 3"),
    (lambda d: build_cache(vendor="Other"), "for vendor 'Other'"),
    (lambda d: build_cache() + b"trailing", "does not match the file size"),
    (lambda d: build_cache()[:-4], "does not match the file size"),
])
def test_decoder_refuses_caches_it_cannot_serve(tmp_path, mutate, match):
    with pytest.raises(preset_cache.CacheError, match=match):
        load(tmp_path, data=mutate(build_cache()))


def test_profiles_flatten_from_a_packed_tree(tmp_path):
    resources = packed_resources(tmp_path)
    flat, version = profiles.flatten(resources, {"machine": "Test Machine",
                                                  "process": "Test Process",
                                                  "filament": "Test Filament"})
    assert version == "02.08.00.15"
    # inherits resolved: the child's layer_height wins, the base's other values survive.
    assert flat["process"]["layer_height"] == "0.28"
    assert flat["process"]["sparse_infill_density"] == "15%"
    assert flat["process"]["sparse_infill_pattern"] == "gyroid"
    # include layered in: the template's G-code arrives, its head keys do not.
    assert flat["machine"]["machine_start_gcode"] == "G28\n"
    assert flat["machine"]["name"] == "Test Machine"
    assert "inherits" not in flat["process"] and "include" not in flat["machine"]


def test_profiles_refuse_an_unreadable_cache_with_the_packed_reason(tmp_path):
    resources = packed_resources(tmp_path, data=b"ZCRO")
    with pytest.raises(profiles.ProfileError, match="packed vendor profiles"):
        profiles.flatten(resources, {"machine": "Test Machine", "process": "Test Process",
                                     "filament": "Test Filament"})


def test_a_json_tree_wins_over_a_cache_beside_it(tmp_path):
    import json
    resources = packed_resources(tmp_path)
    profiles_dir = resources / "profiles"
    (profiles_dir / "BBL").mkdir()
    index = {"version": "09.09.09.09",
             "machine_list": [{"name": "Test Machine", "sub_path": "machine/m.json"}],
             "process_list": [{"name": "Test Process", "sub_path": "process/p.json"}],
             "filament_list": [{"name": "Test Filament", "sub_path": "filament/f.json"}]}
    (profiles_dir / "BBL.json").write_text(json.dumps(index))
    for kind, sub, name in (("machine", "machine/m.json", "Test Machine"),
                            ("process", "process/p.json", "Test Process"),
                            ("filament", "filament/f.json", "Test Filament")):
        path = profiles_dir / "BBL" / sub
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": kind, "name": name, "from": "system",
                                    "instantiation": "true", "marker": "json tree"}))
    flat, version = profiles.flatten(resources, {"machine": "Test Machine",
                                                 "process": "Test Process",
                                                 "filament": "Test Filament"})
    assert version == "09.09.09.09"
    assert all(flat[kind]["marker"] == "json tree" for kind in flat)
