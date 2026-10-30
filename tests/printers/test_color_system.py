"""The per-model color architecture table (issue #656, Stage 1).

Every registered model names exactly one color_system class; the adapter
properties and the counts in its own defaults must agree with it. This is a
characterization surface only: it pins the classification, not any behavior.
"""
import pytest

from print_handy import printers
from print_handy.printers.base import COLOR_SYSTEMS, PrinterModel

# The only non-single models in this stage. The Prusa XL and the Bambu AMS
# models stay "single" here by the issue's own scoping: classifying them is
# named follow-up work, not a silent omission.
EXPECTED = {
    "flashforge.ad5x": "multi_slot",
    "flashforge_stock.ad5x": "multi_slot",
    "flashforge.creator5": "multi_tool",
    "flashforge.creator5_pro": "multi_tool",
}


def test_every_model_names_its_class():
    assert len(printers.MODELS) == 83
    for key, model in printers.MODELS.items():
        assert model.color_system in COLOR_SYSTEMS, key
        assert model.color_system == EXPECTED.get(key, "single"), key
    counts = {name: sum(1 for m in printers.MODELS.values() if m.color_system == name)
              for name in COLOR_SYSTEMS}
    assert counts == {"single": 79, "multi_slot": 2, "multi_tool": 2}


def test_class_agrees_with_the_model_counts():
    for key, model in printers.MODELS.items():
        printer = model.defaults()["printer"]
        ifs_slots = int(printer.get("ifs_slots", 1))
        tool_count = int(printer.get("tool_count", 1))
        assert (ifs_slots > 1) == (model.color_system == "multi_slot"), key
        assert (tool_count > 1) == (model.color_system == "multi_tool"), key


def test_adapter_properties_derive_from_the_class():
    for key, model in printers.MODELS.items():
        adapter = model.adapter({"printer": {"model": key}}, model)
        assert adapter.color_system == model.color_system, key
        assert adapter.multi_slot == (model.color_system == "multi_slot"), key
        assert adapter.multi_tool == (model.color_system == "multi_tool"), key


def _model(**overrides):
    base = dict(key="test.model", label="Test", adapter=printers.MODELS["klipper.generic"].adapter,
                templates="klipper_generic", settings={"printer": {}})
    base.update(overrides)
    return PrinterModel(**base)


def test_contradictory_models_are_refused():
    with pytest.raises(ValueError, match="color_system"):
        _model(color_system="rainbow")
    with pytest.raises(ValueError, match="multi_slot"):
        _model(settings={"printer": {"ifs_slots": 4}})  # slots without the class
    with pytest.raises(ValueError, match="multi_tool"):
        _model(settings={"printer": {"tool_count": 4}})  # tools without the class
    with pytest.raises(ValueError, match="multi_slot"):
        _model(color_system="multi_slot")  # the class without the slots
    with pytest.raises(ValueError, match="multi_tool"):
        _model(color_system="multi_tool")  # the class without the tools
