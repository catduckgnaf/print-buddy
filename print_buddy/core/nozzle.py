"""Nozzle sizes, nozzle types, and material compatibility guards.

Issue #59: nozzle size and nozzle type as real settings (0.2 to 0.8 mm; brass,
hardened steel, ruby, tungsten carbide, diamond PCD).
"""
from __future__ import annotations

import re
from typing import Sequence

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
    "ruby": "ruby",
    "ruby_tipped": "ruby",
    "ruby tipped": "ruby",
    "tungsten": "tungsten_carbide",
    "tungsten_carbide": "tungsten_carbide",
    "tungsten carbide": "tungsten_carbide",
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


class UntunedNozzleError(RuntimeError, NozzleError):
    """Refusal when slicing with a nozzle size lacking a tuned profile."""


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
