"""One error type, one envelope shape, three exit codes.

`1` is an object-level negative (gate refused, digest conflict); `2` is a
request-level failure (bad configuration, protocol mismatch, network). The
distinction is the whole point: a tool must be able to tell "the project is
not ready" from "I could not ask".
"""
from .codes import DIAGNOSTICS


class RegistryError(Exception):
    """A registered diagnostic raised at a command boundary."""

    def __init__(self, code: str, message: str, *, path: str = "",
                 hint: str = "", exit_code: int = 2):
        if code not in DIAGNOSTICS:
            # An unregistered code is an implementation defect, not a runtime
            # condition; fail loudly during development instead of drifting.
            raise AssertionError(f"unregistered diagnostic code: {code}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.path = path
        self.hint = hint
        self.exit_code = exit_code

    def envelope(self) -> dict:
        diagnostic = {"error_code": self.code, "message": self.message}
        if self.path:
            diagnostic["path"] = self.path
        if self.hint:
            diagnostic["hint"] = self.hint
        return {"diagnostic": diagnostic}
