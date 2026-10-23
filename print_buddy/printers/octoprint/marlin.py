"""Marlin support uses OctoPrint's serial connection, not direct USB/serial."""
from ..base import PrinterModel
from ..klipper.generic import MODEL as KLIPPER
from .adapter import OctoPrintAdapter

MODEL = PrinterModel(
    key='octoprint.marlin', label='Marlin via OctoPrint', adapter=OctoPrintAdapter,
    templates='octoprint_marlin',
    settings={**KLIPPER.defaults(), 'printer': {
        **KLIPPER.settings['printer'], 'name': 'Marlin via OctoPrint', 'firmware': 'Marlin',
    }, 'orca': {'templates': 'print_buddy/templates/orca/octoprint_marlin'}},
)
