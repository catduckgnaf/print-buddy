"""Optional Web UI support (#286).

Stage 1 is the config core: the declarative field catalog
(:mod:`print_buddy.webui.catalog`) and the provenance read / validated
write-back API over the YAML settings file
(:mod:`print_buddy.webui.config`). Stage 2 adds the read-only status
server (:mod:`print_buddy.webui.status` for the snapshot,
:mod:`print_buddy.webui.server` for the stdlib HTTP server and the
``python3 -m print_buddy.webui`` entry point). The picker configuration
page is stage 3.
"""
from __future__ import annotations

from .catalog import CATALOG, KINDS, Field, choices_for, field_by_id
from .config import (DEFAULT, ENVIRONMENT, HOME_CONFIG, MODEL_DEFAULT, SETTINGS_FILE,
                     FieldValue, WebUIConfigError, read_field, read_fields,
                     settings_file_path, write_changes)

__all__ = [
    "CATALOG", "KINDS", "Field", "choices_for", "field_by_id",
    "DEFAULT", "ENVIRONMENT", "HOME_CONFIG", "MODEL_DEFAULT", "SETTINGS_FILE",
    "FieldValue", "WebUIConfigError", "read_field", "read_fields",
    "settings_file_path", "write_changes",
]
