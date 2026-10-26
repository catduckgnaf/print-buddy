"""``python3 -m print_buddy.webui`` — run the Web UI status server (#286).

Exits 2 with a clear message when the Web UI is disabled, has no port,
or would bind beyond loopback without an access token; the Stage 4
supervisor child calls this the same way.
"""
from __future__ import annotations

import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main())
