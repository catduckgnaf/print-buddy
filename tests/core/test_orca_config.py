"""Orca vector config parsing: material names with spaces are quoted in G-code."""
import pytest

from print_handy.core import gcode_3mf
from print_handy.core.orca_config import split_config_list
from print_handy.printers.bambulab import ams_mapping, guard


@pytest.mark.parametrize("value, expected", [
    ("PLA", ["PLA"]),
    ("PLA+;PLA;PLA", ["PLA+", "PLA", "PLA"]),
    ('"Silk PLA"', ["Silk PLA"]),
    ('PLA+;"Silk PLA";PETG', ["PLA+", "Silk PLA", "PETG"]),
    ('"A;B";C', ["A;B", "C"]),
    ('"say \\"hi\\""', ['say "hi"']),
    ("PLA;;PLA", ["PLA", "", "PLA"]),
    (None, []),
])
def test_split_config_list_unquotes_like_orca_writes(value, expected):
    assert split_config_list(value) == expected


def test_unterminated_quote_is_an_error():
    with pytest.raises(ValueError):
        split_config_list('"Silk PLA')


QUOTED = '; filament_type = PLA;"Silk PLA"\n'


def test_bambu_guard_reads_quoted_materials():
    assert guard._materials(QUOTED) == ["PLA", "Silk PLA"]
    assert guard._materials('; filament_type = "broken\n') == []


def test_gcode_3mf_and_ams_mapping_read_quoted_materials():
    assert gcode_3mf._header_list(QUOTED, "filament_type") == ["PLA", "Silk PLA"]
    assert [r["material"] for r in ams_mapping.requirements_from_gcode(QUOTED)] == ["PLA", "Silk PLA"]
