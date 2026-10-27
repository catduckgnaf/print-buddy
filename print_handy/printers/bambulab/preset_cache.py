"""Reader for OrcaSlicer's packed vendor preset caches (`<Vendor>.opc`, OrcaSlicer 2.5+).

OrcaSlicer 2.5 stopped shipping the vendor profiles as a JSON tree
(`profiles/<Vendor>.json` plus `profiles/<Vendor>/*.json`): an installed resources folder now
holds one binary cache per vendor (`profiles/<Vendor>.opc`, Orca's "System Preset Cache",
format version 2) next to the vendor's cover images. The cache stores every preset in source
form — the same per-file config diff, `inherits` and `include` names the JSON files state —
keyed through a per-file dictionary of option names and types, so this module can reconstruct
source dicts equivalent to the JSON files and `profiles.py` resolves them through the exact
same pipeline (and the identity fingerprints recorded in facts.py cover this packaging too).

The reconstruction is semantic, not byte-faithful to a JSON tree: Orca's own cache build drops
options its config definitions do not know (Bambu-fork-only keys in the BBL tree, for example)
and applies its option renames, so a packed install flattens differently from a source
checkout of the same release. Both packagings' identities are recorded in facts.py.

Wire format (from OrcaSlicer's PresetCacheFormat at the pinned release; cereal binary
encoding, little-endian, strings and vectors carry a uint64 length):

    header   magic "ZCRO", format version, body size, body CRC32 (20 bytes)
    body     format version, vendor name, vendor version (the "stamps")
             option dictionary: key names, per-key ConfigOptionType, enum value names
             the vendor profile (names/models only are parsed; the rest is skipped in step)
             process, filament and machine preset entries, in that order
             the parse-error count the cache build recorded

Every gate Orca itself applies is applied here too — magic, format version, body size, CRC,
vendor name — plus full-consumption: a cache that does not parse to its last byte is refused.
Values are rendered back to the JSON token forms Orca's preset files use (numbers as bare
decimals, percents with a trailing %, points as "XxY", a nullable option's nil as "nil"), so
the flattened profiles are the ones OrcaSlicer itself loads from the cache.
"""
from __future__ import annotations

import copy
import math
import struct
import zlib

MAGIC = 0x4F52435A  # "ZCRO" on disk
FORMAT_VERSION = 2

# ConfigOptionType values (libslic3r Config.hpp); vector types add 0x4000.
_VECTOR = 0x4000
_FLOAT, _INT, _STRING, _PERCENT, _FLOAT_OR_PERCENT, _POINT, _POINT3, _BOOL, _ENUM = range(1, 10)
_FLOATS, _INTS, _STRINGS, _PERCENTS, _POINTS, _BOOLS, _ENUMS = (
    _FLOAT + _VECTOR, _INT + _VECTOR, _STRING + _VECTOR, _PERCENT + _VECTOR,
    _POINT + _VECTOR, _BOOL + _VECTOR, _ENUM + _VECTOR)
_FLOATS_OR_PERCENTS = _FLOAT_OR_PERCENT + _VECTOR
_POINTS_GROUPS, _INTS_GROUPS = 10 + _VECTOR, 11 + _VECTOR


class CacheError(ValueError):
    """The file is not a preset cache this reader can serve: wrong vendor, corrupt or newer."""


class _Reader:
    def __init__(self, buf):
        self.buf, self.pos = buf, 0

    def take(self, count):
        if self.pos + count > len(self.buf):
            raise CacheError(f"cache ends early (read at byte {self.pos} of {len(self.buf)})")
        out = self.buf[self.pos:self.pos + count]
        self.pos += count
        return out

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def f64(self):
        return struct.unpack("<d", self.take(8))[0]

    def boolean(self):
        return self.u8() != 0

    def string(self):
        length = self.u64()
        if length > 1 << 24:
            raise CacheError(f"implausible string length {length} at byte {self.pos}")
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CacheError(f"invalid UTF-8 string at byte {self.pos}: {exc}") from None

    def vector(self, read_one):
        return [read_one() for _ in range(self.u64())]


class _Entry:
    __slots__ = ("kind", "name", "sub_path", "config", "inherits", "includes", "description",
                 "instantiation", "setting_id", "filament_id", "renamed_from")


class VendorCache:
    """One vendor's decoded cache: its version and every preset as a JSON-form source dict."""

    def __init__(self, version, sources):
        self.version = version        # in the vendor index's form, e.g. "02.08.00.15"
        self.sources = sources        # {preset name: source dict}, all three kinds together

    def source(self, name):
        return copy.deepcopy(self.sources[name])


def _number(value):
    """A typed double as Orca's JSON preset files write it: bare decimal, nil for a null."""
    if math.isnan(value):
        return "nil"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _render(option_type, value):
    """One typed config value back in the JSON token form the vendor JSON files use."""
    if option_type == _FLOAT:
        return _number(value)
    if option_type == _PERCENT:
        return "nil" if isinstance(value, float) and math.isnan(value) else _number(value) + "%"
    if option_type == _INT:
        return str(value)
    if option_type == _STRING:
        return value
    if option_type == _BOOL:
        return "1" if value else "0"
    if option_type == _ENUM:
        # A named value renders as its name; an unnamed one is a nullable option's nil
        # (its raw int is an internal sentinel), which the JSON files write as "nil".
        return value if isinstance(value, str) else "nil"
    if option_type == _FLOAT_OR_PERCENT:
        number, percent = value
        return _number(number) + ("%" if percent else "")
    if option_type == _POINT:
        return f"{_number(value[0])}x{_number(value[1])}"
    if option_type == _POINT3:
        return f"{_number(value[0])}x{_number(value[1])}x{_number(value[2])}"
    if option_type == _FLOATS:
        return [_number(v) for v in value]
    if option_type == _PERCENTS:
        return ["nil" if isinstance(v, float) and math.isnan(v) else _number(v) + "%" for v in value]
    if option_type == _INTS:
        return [str(v) for v in value]
    if option_type == _STRINGS:
        return list(value)
    if option_type == _BOOLS:
        return ["1" if v else "0" for v in value]
    if option_type == _ENUMS:
        return [_render(_ENUM, v) for v in value]
    if option_type == _FLOATS_OR_PERCENTS:
        return [_number(v) + ("%" if p else "") for v, p in value]
    if option_type == _POINTS:
        return [f"{_number(x)}x{_number(y)}" for x, y in value]
    if option_type == _POINTS_GROUPS:
        return [";".join(f"{_number(x)}x{_number(y)}" for x, y in group) for group in value]
    if option_type == _INTS_GROUPS:
        return [";".join(str(i) for i in group) for group in value]
    raise CacheError(f"unknown option type {option_type:#x} in the cache dictionary")


class _Decoder:
    def __init__(self, body):
        self.reader = _Reader(body)
        self.keys, self.types, self.enum_values = [], [], []

    def value(self, option_type):
        r = self.reader
        if option_type in (_FLOAT, _PERCENT):
            return r.f64()
        if option_type in (_FLOATS, _PERCENTS):
            return r.vector(r.f64)
        if option_type == _INT:
            return r.i32()
        if option_type == _INTS:
            return r.vector(r.i32)
        if option_type == _STRING:
            return r.string()
        if option_type == _STRINGS:
            return r.vector(r.string)
        if option_type == _FLOAT_OR_PERCENT:
            return (r.f64(), r.boolean())
        if option_type == _FLOATS_OR_PERCENTS:
            return r.vector(lambda: (r.f64(), r.boolean()))
        if option_type == _POINT:
            return (r.f64(), r.f64())
        if option_type == _POINTS:
            return r.vector(lambda: (r.f64(), r.f64()))
        if option_type == _POINT3:
            return (r.f64(), r.f64(), r.f64())
        if option_type == _BOOL:
            return r.boolean()
        if option_type == _BOOLS:
            return r.vector(r.boolean)
        if option_type in (_ENUM, _ENUMS):
            count = r.u32()
            if option_type == _ENUM and count != 1:
                raise CacheError("a scalar enum option carries more than one value")
            values = []
            for _ in range(count):
                index = r.u16()
                if index == 0:  # the unnamed-enum slot: the raw int32 follows verbatim
                    values.append(("__raw__", r.i32()))
                elif index < len(self.enum_values):
                    values.append(self.enum_values[index])
                else:
                    raise CacheError("enum value index past the end of the cache dictionary")
            return values[0] if option_type == _ENUM else values
        if option_type == _POINTS_GROUPS:
            return r.vector(lambda: r.vector(lambda: (r.f64(), r.f64())))
        if option_type == _INTS_GROUPS:
            return r.vector(lambda: r.vector(r.i32))
        raise CacheError(f"unknown option type {option_type:#x} in the cache dictionary")

    def config(self):
        out = {}
        for _ in range(self.reader.u32()):
            index = self.reader.u16()
            if index >= len(self.keys):
                raise CacheError("option index past the end of the cache dictionary")
            out[self.keys[index]] = self.value(self.types[index])
        return out

    def entry(self, kind):
        r = self.reader
        entry = _Entry()
        entry.kind = kind
        entry.name = r.string()
        entry.sub_path = r.string()
        entry.config = self.config()
        entry.inherits = r.string()
        entry.includes = r.vector(r.string)
        entry.description = r.string()
        entry.instantiation = r.string()
        entry.setting_id = r.string()
        entry.filament_id = r.string()
        entry.renamed_from = r.vector(r.string)
        return entry

    def skip_vendor_profiles(self):
        """Walk the VendorMap in step; Print Handy needs none of it, only what follows it."""
        r = self.reader
        for _ in range(r.u64()):
            r.string()          # the map key (vendor name)
            r.string()          # VendorProfile: name
            r.string()          # id
            r.string()          # config_version (a Semver, written as its standard string)
            r.string()          # config_update_url
            r.string()          # changelog_url
            for _ in range(r.u64()):  # models
                r.string()      # id
                r.string()      # name
                r.string()      # model_id
                r.u8()          # technology (an enum on one byte)
                r.string()      # family
                for _ in range(r.u64()):  # variants
                    r.string()  # variant name
                r.vector(r.string)         # default_materials
                r.vector(r.string)         # not_support_bed_types
                for _ in range(9):         # bed/texture fields and hotend_model
                    r.string()
            r.vector(r.string)  # default_filaments
            r.vector(r.string)  # default_sla_materials


def _source_dict(entry, types_by_key):
    """The preset's source dict in the form its JSON file states it."""
    out = {"type": entry.kind, "name": entry.name, "from": "system",
           "instantiation": entry.instantiation}
    if entry.inherits:
        out["inherits"] = entry.inherits
    if entry.includes:
        out["include"] = list(entry.includes)
    if entry.description:
        out["description"] = entry.description
    if entry.setting_id:
        out["setting_id"] = entry.setting_id
    if entry.filament_id:
        out["filament_id"] = entry.filament_id
    if entry.renamed_from:
        out["renamed_from"] = list(entry.renamed_from)
    for key, value in entry.config.items():
        out[key] = _render(types_by_key[key], value)
    return out


def _index_version(stamp):
    """The cache stamps versions unpadded ("2.8.0.15"); the vendor index zero-pads ("02.08.00.15")."""
    return ".".join(f"{int(part):02d}" if part.isdigit() else part for part in stamp.split("."))


def load(path, vendor):
    """Decode the `<vendor>.opc` at path into a VendorCache, or raise CacheError."""
    try:
        data = open(path, "rb").read()
    except OSError as exc:
        raise CacheError(f"cannot read {path}: {exc}") from None
    if len(data) < 20:
        raise CacheError("the file is shorter than the preset cache header")
    magic, version, size, crc = struct.unpack_from("<IIQI", data, 0)
    if magic != MAGIC:
        raise CacheError("the file is not an OrcaSlicer preset cache (bad magic)")
    if version != FORMAT_VERSION:
        raise CacheError(f"preset cache format version {version} is not supported "
                         f"(this reader understands version {FORMAT_VERSION})")
    body = data[20:]
    if size != len(body):
        raise CacheError("the cache body size does not match the file size")
    if zlib.crc32(body) != crc:
        raise CacheError("the cache fails its CRC check")
    decoder = _Decoder(body)
    r = decoder.reader
    if r.u32() != FORMAT_VERSION:
        raise CacheError("the cache body is not a format version this reader understands")
    name = r.string()
    stamp = r.string()
    if name != vendor:
        raise CacheError(f"the cache is for vendor {name!r}, not {vendor!r}")
    decoder.keys = r.vector(r.string)
    decoder.types = r.vector(r.u16)
    if len(decoder.keys) != len(decoder.types):
        raise CacheError("the cache dictionary's key and type tables differ in length")
    decoder.enum_values = r.vector(r.string)
    if not decoder.enum_values or decoder.enum_values[0] != "":
        raise CacheError("the cache dictionary is missing its unnamed-enum slot")
    decoder.skip_vendor_profiles()
    types_by_key = dict(zip(decoder.keys, decoder.types))
    sources = {}
    for kind in ("process", "filament", "machine"):  # the cache's own write order
        for _ in range(r.u32()):
            entry = decoder.entry(kind)
            if entry.name in sources:
                raise CacheError(f"the cache carries preset {entry.name!r} twice")
            sources[entry.name] = _source_dict(entry, types_by_key)
    r.u64()  # the parse-error count the cache build recorded
    if r.pos != len(body):
        raise CacheError("the cache has trailing bytes this reader cannot account for")
    return VendorCache(_index_version(stamp), sources)
