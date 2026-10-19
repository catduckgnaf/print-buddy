import copy
import unittest
from unittest import mock
from print_buddy.core import printer_state

class OffsetAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.st = {'calibration_authority': {'mode': 'native', 'operator_confirmed': True}, 'calibration_baseline': {'native_zProbeOffset': 0.025, 'probe_z_offset': -0.25}, 'z_offset_mm': None, 'z_offset_verified': False}
    def test_native_confirmed_baseline_does_not_need_screenless_offset(self):
        self.assertEqual(printer_state.offset_authority_problems(self.st, {'display_off': 0}, {'leftExtruderOffset': {'zProbeOffset': 0.025}}), [])
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st}
        text = printer_state.summary(state, "native")
        self.assertIn("native zProbeOffset 0.025", text)
        self.assertNotIn("screenless user offset None", text)

    def test_native_zero_offset_is_a_valid_display_value(self):
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st,
                 'calibration_baseline': {'native_zProbeOffset': 0.0}}
        self.assertIn("native zProbeOffset 0.0", printer_state.summary(state, "native"))

    def test_screenless_none_offset_is_not_reported_as_native_calibration_failure(self):
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st}
        text = printer_state.summary(state, "screenless")
        self.assertIn("screenless user offset None (unverified)", text)
    def test_screenless_none_offset_does_not_claim_failed_live_validation(self):
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st}
        text = printer_state.summary(state, "screenless")
        self.assertIn("screenless user offset None (unverified)", text)
        self.assertNotIn("strict calibration validation failed", text)

    def test_screenless_valid_live_check_is_not_reported_as_failure(self):
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st,
                 'calibration_authority': {'mode': 'screenless', 'operator_confirmed': True},
                 'z_offset_mm': -0.005, 'z_offset_verified': True}
        variables = {'display_off': 1, 'load_zoffset': 1, 'gcode_offsets': {'z': -0.005}}
        self.assertEqual(printer_state.offset_authority_problems(state, variables, {}), [])
        text = printer_state.summary(state, "screenless")
        self.assertNotIn("strict calibration validation failed", text)

    def test_screenless_failed_live_validation_can_be_reported(self):
        state = {'nozzle': {'diameter_mm': 0.4, 'type': 'brass'}, 'spool': {'spoolman_id': 1, 'name': 'test', 'material': 'PLA'},
                 'temps_c': {'nozzle': 200, 'bed': 60}, **self.st}
        self.assertIn("strict calibration validation failed", printer_state.summary(state, "screenless", False))

    def test_native_mismatch_fails(self):
        self.assertTrue(printer_state.offset_authority_problems(self.st, {'display_off': 0}, {'leftExtruderOffset': {'zProbeOffset': -0.005}}))
    def test_unknown_mode_fails(self):
        self.assertTrue(printer_state.offset_authority_problems(self.st, {}, {}))
    def test_screenless_cannot_borrow_native_confirmation(self):
        self.assertTrue(printer_state.offset_authority_problems(self.st, {'display_off': 1, 'load_zoffset': 1, 'gcode_offsets': {'z': -0.005}}, {}))
    def test_nonfinite_native_fails(self):
        for v in (None, True, float('nan'), float('inf')):
            self.assertTrue(printer_state.offset_authority_problems(self.st, {'display_off': 0}, {'leftExtruderOffset': {'zProbeOffset': v}}))
    def test_screenless_scoped_confirmation(self):
        self.st['calibration_authority'] = {'mode': 'screenless', 'operator_confirmed': True}
        self.st['z_offset_mm'] = -0.005
        self.st['z_offset_verified'] = True
        self.assertEqual(printer_state.offset_authority_problems(self.st, {'display_off': 1, 'load_zoffset': 1, 'gcode_offsets': {'z': -0.005}}, {}), [])

    def test_nozzle_change_invalidates_native_authority(self):
        self.st.update({'nozzle': {'diameter_mm': 0.4, 'type': 'stock'}, 'spool': {'spoolman_id': 12, 'name': 'green', 'material': 'PLA'}, 'temps_c': {'nozzle': 210, 'bed': 60}, 'moonraker_url': 'unused', 'spoolman_url': 'unused'})
        with mock.patch.object(printer_state, 'load', return_value=self.st), mock.patch.object(printer_state, 'save'), mock.patch('sys.argv', ['printer_state.py', 'set', '--nozzle', '0.4', '--no-sync-klipper']):
            printer_state.main()
        self.assertIsNone(self.st['z_offset_mm'])
        self.assertFalse(self.st['calibration_authority']['operator_confirmed'])
        self.assertTrue(printer_state.offset_authority_problems(self.st, {'display_off': 0}, {'leftExtruderOffset': {'zProbeOffset': 0.025}}))

if __name__ == '__main__':
    unittest.main()
