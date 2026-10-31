"""Bambu tray and profile vocabulary (2026-10-31 audit): tray_type and sub-brand labels the AMS reports
must resolve through printer_state.material_family, so they match Spoolman labels, pick a vendor profile
key, and meet the A1 not-recommended list. Offline; no printer, slicer or service."""
import pytest

from print_handy.printers.bambulab import ams_mapping, profiles

from .test_bambulab_a1 import a1_gcode, a1_profiles, problems  # noqa: F401  (a1_profiles: autouse fixture)


def snapshot(*trays):
    """A LAN snapshot with one AMS unit holding the given tray dicts (slot ids 0..)."""
    return {"print": {"ams": {"ams": [{"id": "0", "tray": [{"id": str(i), **t} for i, t in enumerate(trays)]}]}}}


def mapped(job_material, **tray):
    trays = ams_mapping.trays_from_snapshot(snapshot(tray))
    return ams_mapping.resolve([{"material": job_material, "extruder": None}], trays)


@pytest.mark.parametrize("tray_type, job_material", [
    ("PET-CF", "PETG-CF"), ("PET-CF", "PET-CF"), ("PAHT-CF", "PA-CF"), ("PA6-CF", "PA-CF"),
    ("PA6-CF", "PA12-CF"), ("PETG-CF", "PET-CF"), ("PLA-CF", "PLA-CF"), ("PLA", "Silk Rainbow PLA"),
    ("PLA", "Wood PLA"), ("TPU", "TPU 95A"), ("PLA-S", "Support for PLA"), ("PA-S", "PA-S"),
])
def test_a_bambu_tray_type_matches_the_spoolman_label_for_the_same_filament(tray_type, job_material):
    assert mapped(job_material, tray_type=tray_type) == [0]


@pytest.mark.parametrize("tray_type, job_material", [
    ("PLA-S", "PLA"), ("PA-S", "PA"), ("PET-CF", "PETG"), ("PAHT-CF", "PA"), ("PLA-CF", "PLA"),
    ("PCTG", "PETG"), ("PETG HF", "PETG"),
])
def test_a_different_filament_never_matches(tray_type, job_material):
    with pytest.raises(ams_mapping.MappingError):
        mapped(job_material, tray_type=tray_type)


def test_the_sub_brand_label_is_used_when_the_tray_reports_no_type():
    assert mapped("PLA", tray_sub_brands="Bambu PLA Basic") == [0]
    assert mapped("Silk PLA", tray_sub_brands="Bambu PLA Silk") == [0]
    assert mapped("PLA-CF", tray_sub_brands="Bambu PLA-CF") == [0]


@pytest.mark.parametrize("material, key", [
    ("PLA", "PLA"), ("PLA-CF", "PLA"), ("Silk PLA-CF", "PLA"), ("Wood PLA", "PLA"), ("PETG", "PETG"),
    ("PET", "PETG"), ("PET-CF", "PETG"), ("PETG-CF", "PETG"), ("TPU 95A", "TPU"), ("PA6-CF", "PA"),
    ("PAHT-CF", "PA"), ("PA12", "PA"), ("Bambu PLA Basic", "PLA"),
])
def test_material_key_routes_every_label_through_the_material_family(material, key):
    assert profiles.material_key(material) == key


@pytest.mark.parametrize("material", ["PETG-HF", "PLA-S", "PA-S", "High Speed PLA", "PCTG"])
def test_material_key_gives_refused_labels_no_checked_profile_key(material):
    assert profiles.material_key(material) not in ("PLA", "PETG", "TPU", "PVA", "PA")


@pytest.mark.parametrize("material", ["PET-CF", "PAHT-CF", "PA6-CF", "PA12-CF", "PA", "PC", "ABS", "ASA"])
def test_the_a1_not_recommended_list_catches_the_reinforced_grades(material):
    found = problems(a1_gcode(material=material))
    assert any(f"{material} is not recommended by Bambu Lab for the" in p for p in found), found


@pytest.mark.parametrize("material", ["PET", "PETG", "PLA", "TPU 95A", "Silk PLA"])
def test_the_a1_not_recommended_list_leaves_the_allowed_materials_alone(material):
    assert not any("not recommended" in p for p in problems(a1_gcode(material=material)))


def test_an_unreadable_embedded_nozzle_type_defaults_to_hardened_steel_like_everything_else(monkeypatch):
    from print_handy import settings
    from .test_bambulab_a1 import state
    base = settings.current()
    monkeypatch.setattr(settings, "current",
                        lambda: {**base, "nozzle_temp_offsets": {"hardened_steel": 8, "stainless_steel": 0}})
    st = state()
    st["temps_c"]["nozzle"] = 210
    found = problems(a1_gcode(nozzle_type="bogus", hotend=210), st)
    assert any("invalid embedded nozzle_type" in p for p in found)
    assert any("effective nozzle temperature 218 C" in p for p in found), found
