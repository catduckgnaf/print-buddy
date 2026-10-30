"""Safe slice explanations, including failures returned by a worker process.

Technical messages belong in receipts and logs. Chat uses this finite vocabulary,
never stderr, exception text, paths or model names supplied by a slicer.
"""
from dataclasses import dataclass
import subprocess

from .. import diagnostics


class SliceFailure(RuntimeError):
    """A failure identified at the boundary that actually knows what failed."""

    CATEGORIES = {'unknown': 'unknown', 'engine': 'unknown', 'conflict': 'configuration', 'timeout': 'transient',
                  'launch': 'configuration', 'layout': 'configuration',
                  'guard': 'configuration', 'output': 'programming',
                  'recipe': 'configuration'}

    def __init__(self, message, *, kind, slicer=None, returncode=None):
        super().__init__(message)
        self.kind = kind if kind in self.CATEGORIES else 'unknown'
        self.slicer = slicer if slicer in ('OrcaSlicer', 'Bambu Studio', 'Flash Studio',
                                          'OrcaSlicer and Bambu Studio') else 'The slicer'
        self.returncode = returncode if type(returncode) is int else None
        self.diagnostic_category = self.CATEGORIES[self.kind]

    def as_dict(self):
        return {'message': str(self), 'kind': self.kind, 'slicer': self.slicer, 'returncode': self.returncode}

    @classmethod
    def from_dict(cls, data):
        return cls(str(data.get('message') or 'slice failed'),
                   kind=data.get('kind'), slicer=data.get('slicer'), returncode=data.get('returncode'))


@dataclass(frozen=True)
class Explanation:
    plain: str
    next_step: str
    retryable: bool = False


BUNDLE = 'Run `/print-handy bundle` and attach the diagnostics bundle to a bug report.'


def explain(exc):
    """A cause and useful next step, with retry only when it may help.

    Unknown failures stay honestly unknown, but tell the operator how to collect
    evidence. The existing single, slice-only retry remains available for them.
    """
    known = diagnostics.known_cause(exc)
    if known is not None:
        return Explanation(known.cause, known.remedy,
                           known.category == diagnostics.Category.TRANSIENT)
    kind = exc.kind if isinstance(exc, SliceFailure) else None
    name = exc.slicer if isinstance(exc, SliceFailure) else 'The slicer'
    error_type = getattr(exc, 'worker_error_type', type(exc).__name__)
    if kind == 'timeout' or isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)) or error_type in (
            'TimeoutExpired', 'TimeoutError'):
        return Explanation(f'{name} exceeded its time limit before finishing the slice.',
                           'You can retry the slice once without printing. If it happens again, ' + BUNDLE, True)
    if kind == 'engine':
        detail = f' (exit code {exc.returncode})' if exc.returncode is not None else ''
        return Explanation(f'{name} failed or produced no usable G-code{detail}.',
                           BUNDLE + ' The saved slicer logs contain its detailed result.')
    if kind == 'conflict':
        return Explanation(f'{name} detected conflicting toolpaths on the plate.',
                           'Separate overlapping parts or prepare fewer copies, then try again. ' + BUNDLE)
    if kind == 'launch' or isinstance(exc, FileNotFoundError):
        return Explanation('The slicer or a required job file could not be opened.',
                           'Run `/print-handy debugging` to check the slicer installation and saved files. ' + BUNDLE)
    if kind == 'layout':
        return Explanation('The requested copies could not be placed on the printer bed.',
                           'Prepare the saved model again with fewer copies. ' + BUNDLE)
    if kind == 'guard':
        return Explanation('A safety check rejected the slicing settings or generated G-code.',
                           BUNDLE + ' Review the reported guard failure before trying again; do not bypass it.')
    if kind == 'output':
        return Explanation(f'{name} produced G-code whose generator could not be verified.', BUNDLE)
    if kind == 'recipe':
        return Explanation('The saved job or printer settings changed after this slice was requested.',
                           'Prepare the saved model again so the slice uses your current choices.')
    if error_type == 'UntunedNozzleError':
        return Explanation('No tuned slicing profile exists for the selected nozzle size.',
                           'Select a nozzle size with a tuned profile, then prepare the model again.')
    if diagnostics.classify(exc) == diagnostics.Category.PROGRAMMING:
        return Explanation('Print Handy encountered an internal error while preparing the slice.', BUNDLE)
    if diagnostics.classify(exc) == diagnostics.Category.CONFIGURATION:
        return Explanation('A slicing configuration check failed.',
                           'Run `/print-handy debugging` and correct the reported configuration. ' + BUNDLE)
    return Explanation('The slice failed, but Print Handy could not identify the cause.',
                       BUNDLE + ' You can also retry the saved model once without printing.', True)


def post(exc, *, retry_failed=False):
    info = explain(exc)
    first = ('The one retry also failed. ' if retry_failed else '') + info.plain
    # A second failure never offers another retry, even for a transient cause.
    next_step = BUNDLE if retry_failed and info.retryable else info.next_step
    return diagnostics.plain_post(first,
        not_happened='No G-code was kept, and nothing was uploaded or started.',
        next_step=next_step, subsystem='slicing', exc=exc)
