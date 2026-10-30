"""Sovol printers that still run stock Marlin, reached through OctoPrint.

A vendor has one connection. These models share OctoPrint's REST path and
Marlin start code. The same machines converted to Klipper are registered
under sovol/ with a different key.
"""
from ..octoprint import VENDOR as OCTOPRINT

VENDOR = OCTOPRINT.derive(key="sovol_marlin", label="Sovol (Marlin/OctoPrint)")
