"""An explicit, JSON-only error protocol; never import a reported exception type."""
from .. import diagnostics
from .slice_failure import SliceFailure
from .slice_refusal import SliceRefusal


class RemoteError(RuntimeError):
    def __init__(self, reply):
        super().__init__(reply.get('error') or 'worker failed without an explanation')
        self.worker_error_type = reply.get('type')
        self.diagnostic_category = reply.get('category', 'unknown')


def encode(exc):
    reply = {'ok': False, 'type': type(exc).__name__, 'error': str(exc),
             'category': diagnostics.classify(exc).value}
    if isinstance(exc, SliceRefusal):
        reply['refusal'] = exc.as_dict()
    elif isinstance(exc, SliceFailure):
        reply['slice_failure'] = exc.as_dict()
    return reply


def decode(reply):
    if isinstance(reply.get('refusal'), dict):
        from .slice_refusal import from_dict
        return from_dict(reply['refusal'])
    if isinstance(reply.get('slice_failure'), dict):
        return SliceFailure.from_dict(reply['slice_failure'])
    # Keep the existing public behavior of these two worker errors.
    cls = {'ValueError': ValueError, 'FileNotFoundError': FileNotFoundError}.get(reply.get('type'))
    return cls(reply.get('error')) if cls else RemoteError(reply)
