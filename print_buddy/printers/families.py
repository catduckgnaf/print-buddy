"""Names of the registered printer families. Kept import-free so settings can validate against it."""
FAMILIES = ("flashforge_zmod", "generic_klipper", "sovol_klipper")
DEFAULT_FAMILY = "flashforge_zmod"
# Orca template subfolder under print_buddy/templates/orca. None: the shared AD5X folder, left in place.
TEMPLATE_SUBDIR = {"flashforge_zmod": None, "generic_klipper": "generic_klipper", "sovol_klipper": "sovol_klipper"}
