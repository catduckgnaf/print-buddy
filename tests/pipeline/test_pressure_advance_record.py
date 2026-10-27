import unittest
from print_handy.core import printer_state


class PressureAdvanceRecordTests(unittest.TestCase):
    def state(self, pa_nozzle="2026-10-16"):
        return {"nozzle": {"diameter_mm": 0.4, "type": "DUROZZLE", "installed": "2026-10-16"},
                "pressure_advance": {"value": 0.065, "nozzle_installed": pa_nozzle}}

    def test_matching_live_value_and_nozzle_passes(self):
        self.assertEqual(printer_state.pressure_advance_problems(self.state(), 0.065), [])

    def test_live_value_drift_is_reported(self):
        self.assertTrue(printer_state.pressure_advance_problems(self.state(), 0.03))

    def test_value_from_previous_nozzle_is_reported(self):
        probs = printer_state.pressure_advance_problems(self.state("2026-09-01"), 0.065)
        self.assertTrue(any("different nozzle" in p for p in probs))

    def test_no_record_is_not_a_failure(self):
        self.assertEqual(printer_state.pressure_advance_problems({"nozzle": {}}, 0.03), [])


if __name__ == "__main__":
    unittest.main()
