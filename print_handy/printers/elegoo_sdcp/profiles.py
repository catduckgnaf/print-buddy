"""Centauri profile generation: the Elegoo pipeline (print_handy/printers/elegoo/profiles.py).

Both Elegoo vendors resolve from the same Orca `Elegoo` vendor tree, so the SDCP package
re-exports the Neptune package's profile machinery unchanged; the Centauri adapter's facts
are what scope it to this printer.
"""
from print_handy.printers.elegoo.profiles import (  # noqa: F401
    ProfileError,
    describe_problems,
    identity,
    install,
    install_hint,
    problems,
    require,
    sha256,
    template_text,
)
