"""Stable machine-readable diagnostics; business exceptions never escape as results."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    error_code: str
    message: str
    path: str = ""
    source_file: str = ""
    severity: str = "error"
    details: dict[str, Any] = field(default_factory=dict)
    release_id: str = ""
    flow_id: str = ""
    node_id: str = ""
    expected: str = ""
    actual: str = ""
    hint: str = ""


class MicroFlowError(Exception):
    def __init__(self, code: str, message: str, path: str = "", **details: Any):
        self.diagnostic = Diagnostic(code, message, path, details=details)
        super().__init__(f"{code}: {message}" + (f" ({path})" if path else ""))


class ContractError(MicroFlowError):
    pass


class PersistenceError(MicroFlowError):
    pass


class Cancelled(Exception):
    """Cooperative cancellation, deliberately distinct from business exceptions."""
