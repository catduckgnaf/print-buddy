"""Narrow default-answer coverage without running the external model corpus."""
import ast
from pathlib import Path

import pytest

from tests.corpus.harness import FakeAdapter, UnansweredPrompt


def default_adapter():
    tree = ast.parse(Path(__file__).with_name("run_external_corpus.py").read_text())
    clicks = next(keyword.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                  for keyword in node.keywords if keyword.arg == "clicks")
    return FakeAdapter(ast.literal_eval(clicks))


@pytest.mark.parametrize("question,choices,expected", [
    ("Inspected 2 parts: Stand, Base. Choose colors for these parts or one color for everything?",
     ["Choose colors for these parts", "One color for everything", "Cancel"], 1),
    ("Inspected 1 part: Body. Keep distinct source regions or explicitly use one color for everything? "
     "Keeping painted regions prints each painted area in the color you pick for it.",
     ["Keep distinct source regions", "One color for everything", "Cancel"], 1),
    ("stand (223 × 223 × 124 mm) does not fit the bed full size.",
     ["100% + supports", "Shrink to 95%", "Cancel"], 1),
])
def test_generic_answers(question, choices, expected):
    assert default_adapter().pick(question, choices) == expected


@pytest.mark.parametrize("question,choices", [
    ("Unexpected approval question", ["Continue", "Cancel"]),
    ("stand does not fit the bed full size.", ["100% + supports", "Cancel"]),
])
def test_unrecognized_or_unavailable_answers_still_fail(question, choices):
    with pytest.raises(UnansweredPrompt):
        default_adapter().pick(question, choices)
