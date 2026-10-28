"""Nozzle sizes, nozzle types, and material compatibility guards.

Issue #59: nozzle size and nozzle type as real settings (0.2 to 0.8 mm; brass,
hardened steel, ruby, tungsten carbide, diamond PCD).
"""
from __future__ import annotations

import re
from typing import Sequence
from dataclasses import dataclass

CANONICAL_NOZZLE_SIZES: tuple[float, ...] = (0.2, 0.25, 0.4, 0.6, 0.8)

CANONICAL_NOZZLE_TYPES: tuple[str, ...] = (
    "brass",
    "hardened_steel",
    "stainless_steel",
    "ruby",
    "tungsten_carbide",
    "diamond",
)

# Known aliases mapped to canonical types
# The installed DUROZZLE label includes size and plating, but its material is tungsten carbide.
# Keep this as an exact alias rather than accepting arbitrary vendor labels.
NOZZLE_TYPE_ALIASES: dict[str, str] = {
    "brass": "brass",
    "copper": "brass",
    "hardened": "hardened_steel",
    "hardened_steel": "hardened_steel",
    "hardened steel": "hardened_steel",
    "steel": "hardened_steel",
    "stainless": "stainless_steel",
    "stainless_steel": "stainless_steel",
    "stainless steel": "stainless_steel",
    "stock": "stainless_steel",
    "ruby": "ruby",
    "ruby_tipped": "ruby",
    "ruby tipped": "ruby",
    "tungsten": "tungsten_carbide",
    "tungsten_carbide": "tungsten_carbide",
    "tungsten carbide": "tungsten_carbide",
    "durozzle tungsten carbide 0.4 (nickel_plated copper)": "tungsten_carbide",
    "diamond": "diamond",
    "diamond_pcd": "diamond",
    "diamond (pcd)": "diamond",
    "pcd": "diamond",
}

# Abrasive material indicators (case-insensitive)
ABRASIVE_KEYWORDS: tuple[str, ...] = (
    "cf",
    "gf",
    "carbon",
    "glass",
    "glow",
    "wood",
    "metal",
)


class NozzleError(ValueError):
    """Base error for nozzle validation failures."""


class AbrasiveNozzleError(NozzleError):
    """Refusal when abrasive filament is paired with a non-abrasive-rated nozzle (e.g. brass)."""


class NozzleTemperatureError(NozzleError):
    """Refusal when printing temperature exceeds nozzle thermal limits."""


class UntunedNozzleError(RuntimeError, NozzleError):
    """Refusal when slicing with a nozzle size lacking a tuned profile."""


@dataclass(frozen=True)
class NozzleProfile:
    """Tuned slicing profile parameters for a specific nozzle diameter."""

    diameter_mm: float
    min_layer_height: float
    max_layer_height: float
    default_layer_height: float
    default_initial_layer_height: float
    retraction_length: float
    line_width: float
    initial_layer_line_width: float
    prime_tower_width: int


TUNED_NOZZLE_PROFILES: dict[float, NozzleProfile] = {
    0.2: NozzleProfile(
        diameter_mm=0.2,
        min_layer_height=0.04,
        max_layer_height=0.14,
        default_layer_height=0.10,
        default_initial_layer_height=0.12,
        retraction_length=1.0,
        line_width=0.21,
        initial_layer_line_width=0.25,
        prime_tower_width=30,
    ),
    0.25: NozzleProfile(
        diameter_mm=0.25,
        min_layer_height=0.05,
        max_layer_height=0.18,
        default_layer_height=0.14,
        default_initial_layer_height=0.16,
        retraction_length=1.0,
        line_width=0.26,
        initial_layer_line_width=0.31,
        prime_tower_width=35,
    ),
    0.4: NozzleProfile(
        diameter_mm=0.4,
        min_layer_height=0.08,
        max_layer_height=0.28,
        default_layer_height=0.24,
        default_initial_layer_height=0.24,
        retraction_length=0.8,
        line_width=0.42,
        initial_layer_line_width=0.50,
        prime_tower_width=45,
    ),
    0.6: NozzleProfile(
        diameter_mm=0.6,
        min_layer_height=0.15,
        max_layer_height=0.42,
        default_layer_height=0.32,
        default_initial_layer_height=0.32,
        retraction_length=1.2,
        line_width=0.63,
        initial_layer_line_width=0.75,
        prime_tower_width=60,
    ),
    0.8: NozzleProfile(
        diameter_mm=0.8,
        min_layer_height=0.24,
        max_layer_height=0.56,
        default_layer_height=0.40,
        default_initial_layer_height=0.40,
        retraction_length=1.5,
        line_width=0.84,
        initial_layer_line_width=1.00,
        prime_tower_width=75,
    ),
}


def _load_nozzle_profiles() -> dict[float, NozzleProfile]:
    from pathlib import Path
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    toml_path = Path(__file__).resolve().parent.parent / "data" / "nozzles.toml"
    profiles: dict[float, NozzleProfile] = {}
    if toml_path.is_file():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            for k, v in data.items():
                try:
                    d = float(k)
                    profiles[d] = NozzleProfile(
                        diameter_mm=float(v.get("diameter_mm", d)),
                        min_layer_height=float(v["min_layer_height"]),
                        max_layer_height=float(v["max_layer_height"]),
                        default_layer_height=float(v["default_layer_height"]),
                        default_initial_layer_height=float(v["default_initial_layer_height"]),
                        retraction_length=float(v["retraction_length"]),
                        line_width=float(v["line_width"]),
                        initial_layer_line_width=float(v["initial_layer_line_width"]),
                        prime_tower_width=int(v.get("prime_tower_width", 45)),
                    )
                except (ValueError, KeyError):
                    continue
        except Exception:
            pass
    if not profiles:
        profiles = TUNED_NOZZLE_PROFILES
    return profiles


def get_tuned_nozzle_profile(diameter_mm: float | int) -> NozzleProfile | None:
    """Return tuned nozzle profile if available for the given diameter."""
    val = float(diameter_mm)
    profiles = _load_nozzle_profiles()
    for d, profile in profiles.items():
        if abs(d - val) < 0.01:
            return profile
    return None


# Thermal and flow defaults are typed in print_handy/data/nozzles.toml.
# Runtime temperature offsets are separately configurable per nozzle type.
def _nozzle_type_defaults() -> dict[str, dict[str, float]]:
    from pathlib import Path
    import tomllib

    path = Path(__file__).resolve().parent.parent / "data" / "nozzles.toml"
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
        rows = data.get("types", {})
        result = {}
        for name in CANONICAL_NOZZLE_TYPES:
            row = rows[name]
            maximum = float(row["max_temperature_c"])
            offset = float(row.get("temp_offset_c", 0.0))
            flow = float(row["flow_multiplier"])
            if not 0 < maximum <= 550 or not -10 <= offset <= 15 or not 0 < flow <= 2:
                raise ValueError(f"invalid nozzle type profile {name!r}")
            result[name] = {"max_temperature_c": maximum, "temp_offset_c": offset,
                            "flow_multiplier": flow}
        return result
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise NozzleError(f"invalid nozzle type configuration in {path}: {exc}") from exc


def get_nozzle_type_adjustments(nozzle_type: str | None) -> dict[str, float]:
    """Return validated thermal and flow characteristics for a nozzle type.

    A per-type offset in ``[nozzle_temp_offsets]`` overrides the data-file default.
    Offsets are bounded to -10..+15 °C; every type defaults to zero.
    """
    norm = normalize_nozzle_type(nozzle_type) if nozzle_type else "hardened_steel"
    values = _nozzle_type_defaults()[norm].copy()
    try:
        from .. import settings
        override = settings.current().get("nozzle_temp_offsets", {}).get(norm, values["temp_offset_c"])
    except (ImportError, AttributeError):
        override = values["temp_offset_c"]
    if isinstance(override, bool) or not isinstance(override, (int, float)) or not -10 <= override <= 15:
        raise NozzleError(f"temperature offset for {norm} must be between -10 and +15 °C, got {override!r}")
    values["temp_offset_c"] = float(override)
    return values


def effective_nozzle_temperature(nozzle_type: str | None, base_temperature_c: float | int) -> float:
    """Resolve requested temperature plus offset, refusing rather than clamping above max."""
    adjustments = get_nozzle_type_adjustments(nozzle_type)
    effective = float(base_temperature_c) + adjustments["temp_offset_c"]
    check_nozzle_temperature_safety(nozzle_type or "hardened_steel", effective)
    return effective


def check_nozzle_temperature_safety(nozzle_type: str, temperature_c: float | int) -> None:
    """Validate the effective requested temperature against the nozzle's safe limit."""
    adj = _nozzle_type_defaults()[normalize_nozzle_type(nozzle_type)]
    max_temp = adj["max_temperature_c"]
    if float(temperature_c) > max_temp:
        raise NozzleTemperatureError(
            f"Requested temperature {temperature_c}°C exceeds maximum safe limit of "
            f"{max_temp:g}°C for {nozzle_type} nozzle."
        )


def normalize_nozzle_type(raw: str) -> str:
    """Normalize a nozzle type string to its canonical identifier.

    Raises NozzleError if the type cannot be mapped.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise NozzleError(f"nozzle type must be a non-empty string, got {raw!r}")
    cleaned = raw.strip().lower().replace("-", "_")
    # Also support space-separated variants
    if cleaned in NOZZLE_TYPE_ALIASES:
        return NOZZLE_TYPE_ALIASES[cleaned]
    with_spaces = cleaned.replace("_", " ")
    if with_spaces in NOZZLE_TYPE_ALIASES:
        return NOZZLE_TYPE_ALIASES[with_spaces]
    valid = ", ".join(CANONICAL_NOZZLE_TYPES)
    raise NozzleError(f"unknown nozzle type {raw!r}; expected one of: {valid}")


def is_abrasive_material(material: str | None) -> bool:
    """Return True if the filament material name indicates abrasive content."""
    if not material or not isinstance(material, str):
        return False
    mat_lower = material.strip().lower()
    # Check word boundaries or token separators like '-', '_', '+'
    tokens = re.split(r"[\s\-_+]+", mat_lower)
    for kw in ABRASIVE_KEYWORDS:
        if kw in tokens or kw in mat_lower:
            return True
    return False


def check_nozzle_material_safety(nozzle_type: str, material: str | None) -> None:
    """Refuse abrasive materials on soft brass nozzles.

    Brass nozzles wear out rapidly with carbon fiber, glass fiber, glow-in-the-dark,
    wood, and metal-fill filaments, destroying dimensional accuracy.
    """
    if not material:
        return
    norm_type = normalize_nozzle_type(nozzle_type)
    if norm_type == "brass" and is_abrasive_material(material):
        raise AbrasiveNozzleError(
            f"Refusing to slice abrasive material '{material}' on a brass nozzle. "
            f"Abrasive filaments cause severe nozzle wear on brass. "
            f"Switch to a hardened steel, ruby, tungsten carbide, or diamond nozzle."
        )


def validate_nozzle_setting(
    diameter_mm: float | str,
    nozzle_type: str | None = None,
    *,
    supported_sizes: Sequence[float] | None = None,
    supported_types: Sequence[str] | None = None,
) -> tuple[float, str]:
    """Validate nozzle diameter and optional nozzle type against supported options.

    Returns (normalized_diameter_mm, normalized_nozzle_type).
    """
    try:
        dia = float(diameter_mm)
    except (TypeError, ValueError):
        raise NozzleError(f"nozzle diameter must be a number, got {diameter_mm!r}")
    if dia <= 0:
        raise NozzleError(f"nozzle diameter must be positive, got {dia}")

    allowed_sizes = supported_sizes if supported_sizes is not None else CANONICAL_NOZZLE_SIZES
    if dia not in allowed_sizes:
        sizes_str = ", ".join(f"{s:g}" for s in sorted(allowed_sizes))
        raise NozzleError(f"nozzle diameter {dia:g} mm is not supported (supported: {sizes_str})")

    norm_type = normalize_nozzle_type(nozzle_type) if nozzle_type else "hardened_steel"
    if supported_types is not None and norm_type not in supported_types:
        types_str = ", ".join(sorted(supported_types))
        raise NozzleError(f"nozzle type '{norm_type}' is not supported (supported: {types_str})")

    return dia, norm_type
