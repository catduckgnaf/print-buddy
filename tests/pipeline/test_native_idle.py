import unittest
from copy import deepcopy
from print_buddy.printers.flashforge.zmod.native_idle import require_idle

class NativeIdleTests(unittest.TestCase):
    def setUp(self):
        self.m = dict(state='ready', print=dict(state='standby'), extruder=dict(target=0), bed=dict(target=0))
        self.n = dict(status='cancel', leftTargetTemp=0, rightTargetTemp=0, platTargetTemp=0, chamberTargetTemp=0, errorCode='', printProgress=0, printDuration=0)
    def test_cancel_is_corroborated_idle(self):
        self.assertTrue(require_idle(self.m,self.n))
    def test_ready_is_corroborated_idle(self):
        self.n['status']='ready'
        self.assertTrue(require_idle(self.m,self.n))
    def test_reject_active_native(self):
        for s in ['printing','paused','unknown']:
            n=deepcopy(self.n); n['status']=s
            with self.assertRaises(RuntimeError): require_idle(self.m,n)
    def test_reject_active_moonraker(self):
        m = deepcopy(self.m)
        m['print']['state']='printing'
        with self.assertRaises(RuntimeError): require_idle(m,self.n)
    def test_reject_heat(self):
        for key in ['leftTargetTemp','rightTargetTemp','platTargetTemp','chamberTargetTemp']:
            n=deepcopy(self.n); n[key]=60
            with self.assertRaises(RuntimeError): require_idle(self.m,n)
    def test_rejection_names_exact_failed_predicate_and_value(self):
        n = deepcopy(self.n)
        n['printDuration'] = 'not-a-number'
        with self.assertRaisesRegex(RuntimeError, r"native printDuration == 0 \(observed 'not-a-number'\)"):
            require_idle(self.m, n)

    def test_rejection_names_moonraker_state_predicate(self):
        m = deepcopy(self.m)
        m['print']['state'] = 'printing'
        with self.assertRaisesRegex(RuntimeError, r"Moonraker print.state == 'standby' \(observed 'printing'\)"):
            require_idle(m, self.n)

    def test_malformed_values_fail_closed_with_diagnostic(self):
        for n in (None, [], {'status':'cancel', 'leftTargetTemp': [], 'rightTargetTemp':0,
                             'platTargetTemp':0, 'chamberTargetTemp':0, 'errorCode':'',
                             'printProgress':0, 'printDuration':0}):
            with self.assertRaisesRegex(RuntimeError, 'REFUSED: idle guard failed'):
                require_idle(self.m, n)

    def test_accepts_numeric_native_activity_zero(self):
        for value in (0, 0.0):
            n = deepcopy(self.n)
            n['printProgress'] = value
            n['printDuration'] = value
            self.assertTrue(require_idle(self.m, n))

    def test_rejects_numeric_string_native_activity_zero(self):
        for key in ('printProgress', 'printDuration'):
            for value in ('0', '0.0'):
                n = deepcopy(self.n)
                n[key] = value
                with self.assertRaisesRegex(RuntimeError, f'native {key} == 0'):
                    require_idle(self.m, n)

    def test_reject_boolean_targets_and_activity(self):
        for key in ('leftTargetTemp', 'rightTargetTemp', 'platTargetTemp', 'chamberTargetTemp',
                    'printProgress', 'printDuration'):
            n = deepcopy(self.n)
            n[key] = False
            with self.assertRaises(RuntimeError):
                require_idle(self.m, n)

    def test_reject_error_or_unknown_activity(self):
        for key,value in [('errorCode','E1'),('errorCode',None),('printProgress',1),('printDuration',2),('printDuration',None)]:
            n=deepcopy(self.n); n[key]=value
            with self.assertRaises(RuntimeError): require_idle(self.m,n)
if __name__=='__main__': unittest.main()
