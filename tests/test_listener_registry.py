"""#299: the listener registry behind the gate, supervisor and healthcheck.

One registry (print_buddy.listeners) maps every vendor connection to its
listener domain: implemented (moonraker, and bambulab_lan since Stage B),
planned (domain known, no listener yet) or none (offline). The planned/none
distinction is what lets the supervisor idle a zero-listener configuration
instead of failing it, while an unresolved configuration still fails
distinctly (#256 semantics).
Offline: registry, fake settings and mocks only.
"""
import importlib.util
import unittest
from unittest import mock

from print_buddy import healthcheck, listeners, printers, settings
from print_buddy.printers import base as printer_base


def data(model):
    return {"printer": {"model": model}}


class RegistryShapeTests(unittest.TestCase):
    def test_every_connection_has_exactly_one_domain(self):
        self.assertEqual(set(listeners.DOMAINS), set(printer_base.CONNECTIONS))
        for connection, domain in listeners.DOMAINS.items():
            with self.subTest(connection=connection):
                self.assertEqual(domain.connection, connection)
                self.assertEqual(domain.name, connection)

    def test_implemented_domains_are_moonraker_and_bambulab(self):
        implemented = [c for c, d in listeners.DOMAINS.items() if d.implemented]
        self.assertEqual(implemented, ["moonraker", "bambulab_lan"])
        self.assertEqual(listeners.implemented_connections(),
                         ("moonraker", "bambulab_lan"))
        # Backwards-compatible name the #256 code and tests already use.
        self.assertEqual(healthcheck.LISTENER_CONNECTIONS,
                         ("moonraker", "bambulab_lan"))

    def test_implemented_domain_points_at_a_real_module_and_runtime(self):
        for connection in ("moonraker", "bambulab_lan"):
            with self.subTest(connection=connection):
                domain = listeners.DOMAINS[connection]
                self.assertIsNotNone(importlib.util.find_spec(domain.module))
                self.assertIsNotNone(domain.runtime)
        self.assertEqual(listeners.DOMAINS["moonraker"].runtime,
                         healthcheck.RUNTIME)
        from print_buddy.printers.bambulab import listener as bambu_listener
        self.assertEqual(listeners.DOMAINS["bambulab_lan"].runtime,
                         bambu_listener.RUNTIME)
        self.assertEqual(listeners.DOMAINS["bambulab_lan"].module,
                         "print_buddy.printers.bambulab.listener")

    def test_planned_and_none_are_distinct_states(self):
        for connection in ("prusalink", "elegoo_sdcp",
                           "octoprint", "flashforge_stock"):
            with self.subTest(connection=connection):
                domain = listeners.DOMAINS[connection]
                self.assertEqual(domain.availability, listeners.PLANNED)
                self.assertIsNone(domain.module)
                self.assertFalse(domain.implemented)
        offline = listeners.DOMAINS["offline"]
        self.assertEqual(offline.availability, listeners.NONE)
        self.assertFalse(offline.implemented)


class RegistryClassificationTests(unittest.TestCase):
    def test_every_registered_model_is_classified_by_its_connection(self):
        for key, model in printers.MODELS.items():
            with self.subTest(model=key):
                domain = healthcheck.listener_domain(data(key))
                self.assertIs(domain, listeners.DOMAINS[model.vendor.connection])
                self.assertEqual(healthcheck.listener_required(data(key)),
                                 domain.availability == listeners.IMPLEMENTED)

    def test_moonraker_models_still_require_the_listener(self):
        # Behaviour-identical pin from #256: the same models, the same answer.
        for model in ("flashforge.ad5x", "klipper.generic", "sovol.sv06",
                      "elegoo.neptune4"):
            with self.subTest(model=model):
                self.assertTrue(healthcheck.listener_required(data(model)))

    def test_bambu_models_require_the_listener(self):
        # #299 Stage B: bambulab_lan flipped from planned to implemented.
        for model in ("bambulab.a1", "bambulab.p1s", "bambulab.x1c",
                      "bambulab.h2s"):
            with self.subTest(model=model):
                self.assertTrue(healthcheck.listener_required(data(model)))

    def test_no_other_model_requires_a_listener_yet(self):
        for model in ("flashforge_stock.ad5x",
                      "octoprint.marlin", "prusa.mk4s", "prusa.coreone",
                      "elegoo_sdcp.centauricarbon"):
            with self.subTest(model=model):
                self.assertFalse(healthcheck.listener_required(data(model)))


class LauncherTests(unittest.TestCase):
    def test_planned_domain_is_nothing_to_run_not_a_failure(self):
        with mock.patch.object(healthcheck, "listener_domain",
                               return_value=listeners.DOMAINS["prusalink"]):
            self.assertEqual(listeners.launch({}), 3)

    def test_bambu_domain_runs_its_registered_module(self):
        with mock.patch.object(healthcheck, "listener_domain",
                               return_value=listeners.DOMAINS["bambulab_lan"]), \
                mock.patch.object(listeners.runpy, "run_module") as run_module:
            self.assertEqual(listeners.launch({}), 0)
        run_module.assert_called_once_with(
            "print_buddy.printers.bambulab.listener", run_name="__main__")

    def test_none_domain_is_nothing_to_run(self):
        with mock.patch.object(healthcheck, "listener_domain",
                               return_value=listeners.DOMAINS["offline"]):
            self.assertEqual(listeners.launch({}), 3)

    def test_implemented_domain_runs_its_registered_module(self):
        with mock.patch.object(healthcheck, "listener_domain",
                               return_value=listeners.DOMAINS["moonraker"]), \
                mock.patch.object(listeners.runpy, "run_module") as run_module:
            self.assertEqual(listeners.launch({}), 0)
        run_module.assert_called_once_with(
            "print_buddy.hermes.moonraker_event_listener", run_name="__main__")

    def test_unresolved_configuration_keeps_the_gate_failure_code(self):
        with mock.patch.object(healthcheck, "listener_domain",
                               side_effect=settings.SettingsError("bad model")):
            self.assertEqual(listeners.main(), 2)


class StatusContractTests(unittest.TestCase):
    def test_adapter_normalised_statuses_fit_the_contract(self):
        from print_buddy.printers.bambulab.adapter import BambuAdapter
        from print_buddy.printers.elegoo_sdcp.adapter import ElegooSdcpAdapter
        from print_buddy.printers.prusa.adapter import PrusaAdapter

        for cls in (BambuAdapter, PrusaAdapter, ElegooSdcpAdapter):
            with self.subTest(adapter=cls.__name__):
                status = object.__new__(cls).normalize_status({})
                self.assertEqual(listeners.validate_status(status), [])
        self.assertEqual(
            listeners.validate_status(printer_base.basic_status({})), [])

    def test_validate_status_flags_contract_breaks(self):
        problems = listeners.validate_status(
            {"state": 3, "filename": "", "progress": 2, "hotend_c": None,
             "bed_c": None})
        self.assertTrue(any("state" in p for p in problems))
        self.assertTrue(any("progress" in p for p in problems))
        self.assertTrue(any("missing" in p
                            for p in listeners.validate_status({})))


if __name__ == "__main__":
    unittest.main()
