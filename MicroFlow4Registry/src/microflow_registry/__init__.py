"""MicroFlow registration projection: snapshot metadata for support platforms.

The package adds no semantics of its own. It reads the CLI's deterministic
envelopes, projects them into ``microflow-registry-v1``, and registers that
projection idempotently by content digest.
"""
from .collect import build_report
from .envelope import canonical, digest, report_digest
from .errors import RegistryError
from .pump import EventPump
from .sink import RecordStream
from .store import Store
from .stream import build_batch, build_frame, validate_batch

__version__ = "0.1.0"
__all__ = ["build_report", "canonical", "digest", "report_digest", "RegistryError",
           "RecordStream", "EventPump", "Store", "build_batch", "build_frame",
           "validate_batch", "__version__"]
