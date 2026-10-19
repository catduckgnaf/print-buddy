"""Offline startup regression; no printer access."""
import pytest
from print_buddy.core.native_startup import normalize, valid

START = 'START_PRINT BED_TEMP=60 EXTRUDER_TEMP=210 MESH=MESH_DATA\n'
PREFIX = 'M190 S60\nM104 S210 T0\n'

@pytest.mark.parametrize('tool', [0, 1])
def test_preserves_initial_tool_and_body(tool):
    body = START + f'G90\nT{tool}\nG1 X10 E1\nM104 S210\n'
    result = normalize(body)
    assert result == PREFIX + body
    assert normalize(result) == result
    assert valid(result, 60, 210)

@pytest.mark.parametrize('text', [
    START + 'T1\nG1 E1\nM104 S210\nM190 S60\n',
    'M104 S210\nM190 S60\n' + START,
    'M140 S60\nM104 S210\n' + START,
    PREFIX.replace('T0', 'T1') + START,
    PREFIX + START.replace('210', '220'),
    PREFIX + START + START,
])
def test_misplaced_missing_or_conflicting_prefix_refused(text):
    assert not valid(text, 60, 210)

@pytest.mark.parametrize('text', ['M190 S70\n' + START, 'M104 S210 T1\n' + START,
                                   START + START, START.replace('60', '60 BED_TEMP=70')])
def test_normalization_conflicts_refused(text):
    with pytest.raises(RuntimeError):
        normalize(text)

def test_prior_successful_immediate_post_start_header():
    text = START + PREFIX + 'T0\nG1 E1\n'
    assert valid(text, 60, 210)
    assert normalize(text) == text


def test_successful_documented_header():
    text = '; HEADER_BLOCK_START\n; HEADER_BLOCK_END\n' + PREFIX + START + 'T0\nG1 E1\n'
    assert valid(text, 60, 210)
    assert normalize(text) == text
