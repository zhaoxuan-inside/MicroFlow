"""Read-only CLI probe: the only way this package learns anything.

Mirrors MicroFlow4MCP: argv list, no shell, JSON envelope out. The CLI entry
is resolved in this order (Spring-style externalized configuration):

    explicit ``prefix`` argument  >  ``MF_REGISTRY_CLI`` env  >  python -m microflow

Capability probing comes before feature use: a command this projection needs
but the installed CLI lacks is a hard refusal, never a silent skip.
"""
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

from .errors import RegistryError

CLI_ENV = "MF_REGISTRY_CLI"
CLI_PROTOCOL = "microflow-cli-v1"
DEFAULT_TIMEOUT_SECONDS = 180
_STDERR_TAIL = 400


@dataclass(frozen=True)
class CliResult:
    code: int
    payload: dict
    stderr: str


class Cli:
    def __init__(self, prefix=None, *, timeout=DEFAULT_TIMEOUT_SECONDS, env=None):
        if prefix:
            self._prefix = list(prefix)
        else:
            configured = os.getenv(CLI_ENV, "").strip()
            self._prefix = shlex.split(configured) if configured else [sys.executable, "-m", "microflow"]
        self._timeout = timeout
        self._env = dict(os.environ if env is None else env)

    @property
    def entry(self) -> str:
        """Human-readable invocation recorded in reports (quoted, shell-free)."""
        return " ".join(shlex.quote(part) for part in self._prefix)

    def call(self, argv, *, protocols=(CLI_PROTOCOL,)) -> CliResult:
        """Run one CLI command and parse its envelope. Raises registered codes."""
        try:
            done = subprocess.run([*self._prefix, *argv], capture_output=True, text=True,
                                  timeout=self._timeout, check=False, env=self._env)
        except subprocess.TimeoutExpired as error:
            raise RegistryError("CLI_TIMEOUT",
                                f"microflow {' '.join(argv)} exceeded {self._timeout}s") from error
        except OSError as error:
            raise RegistryError("CLI_UNAVAILABLE",
                                f"cannot launch {self.entry}: {error}",
                                hint="set MF_REGISTRY_CLI or install microflow4python") from error
        try:
            payload = json.loads(done.stdout)
        except (ValueError, TypeError) as error:
            raise RegistryError(
                "CLI_PROTOCOL_MISMATCH",
                f"microflow {' '.join(argv)} did not print JSON",
                hint=(done.stderr or done.stdout)[-_STDERR_TAIL:].strip()) from error
        if not isinstance(payload, dict) or payload.get("protocol") not in protocols:
            raise RegistryError(
                "CLI_PROTOCOL_MISMATCH",
                f"expected protocol in {list(protocols)}, got {payload.get('protocol')!r}",
                hint="agent and CLI versions are incompatible")
        return CliResult(done.returncode, payload, done.stderr)

    def require(self, argv, *, protocols=(CLI_PROTOCOL,)) -> dict:
        """Run a command that must succeed; a non-zero CLI exit is a request failure."""
        result = self.call(argv, protocols=protocols)
        if result.code != 0:
            diagnostic = result.payload.get("diagnostic") or {}
            code = diagnostic.get("error_code") or "unknown"
            message = diagnostic.get("message") or "CLI returned a failure envelope"
            raise RegistryError(
                "CLI_FAILED", f"{code}: {message}",
                path=str(diagnostic.get("path") or ""),
                hint=str(diagnostic.get("hint") or ""))
        return result.payload
