"""Host-contract push client: snapshots and event batches, no retry storm.

The endpoint speaks ``MicroFlow4Kit/HOST_CONTRACT.md``: POST one scenario
envelope ``{scenario, version, payload, context}`` and receive
``{code, data, message, trace_id}``. Configuration is externalized with
Spring-style precedence: explicit argument > ``MF_REGISTRY_*`` env > default.
"""
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .envelope import dumps
from .errors import RegistryError

SCENARIO = "registry.publish"
SCENARIO_STREAM = "registry.stream"
SCENARIO_VERSION = 1
DEFAULT_ENDPOINT = "http://127.0.0.1:3000/api/v1/dispatch"
DEFAULT_TIMEOUT_SECONDS = 15.0
_RETRY_BACKOFF_SECONDS = 0.5


@dataclass(frozen=True)
class Config:
    endpoint: str
    token: str
    tenant_id: str = ""
    project_id: str = ""
    env_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.token)


def resolve_config(*, endpoint=None, token=None, tenant_id=None, project_id=None,
                   env_key=None) -> Config:
    """Externalized configuration: explicit argument, then environment, then default."""
    return Config(
        endpoint=(endpoint or os.getenv("MF_REGISTRY_ENDPOINT") or DEFAULT_ENDPOINT),
        token=(token if token is not None else os.getenv("MF_REGISTRY_TOKEN", "")),
        tenant_id=(tenant_id if tenant_id is not None else os.getenv("MF_REGISTRY_TENANT", "")),
        project_id=(project_id if project_id is not None else os.getenv("MF_REGISTRY_PROJECT", "")),
        env_key=(env_key if env_key is not None else os.getenv("MF_REGISTRY_ENV_KEY", "")),
    )


def _context(config: Config) -> dict:
    context = {"token": config.token}
    for key, value in (("tenant_id", config.tenant_id), ("project_id", config.project_id),
                       ("env_key", config.env_key)):
        if value:
            context[key] = value
    return context


def build_payload(config: Config, report: dict) -> dict:
    return {"scenario": SCENARIO, "version": SCENARIO_VERSION,
            "payload": {"namespace": report["namespace"], "group": report["group"],
                        "digest": report["digest"],
                        "contentDigest": report.get("contentDigest", ""),
                        "report": report},
            "context": _context(config)}


def build_stream_payload(config: Config, batch: dict) -> dict:
    return {"scenario": SCENARIO_STREAM, "version": SCENARIO_VERSION,
            "payload": {"namespace": batch["namespace"], "group": batch["group"],
                        "contentDigest": batch["contentDigest"],
                        "count": batch["count"], "batch": batch},
            "context": _context(config)}


def _post(config: Config, payload: dict, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        config.endpoint, data=dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Bearer {config.token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RegistryError("PUSH_FAILED", f"cannot reach {config.endpoint}: {error}",
                            hint="the local outbox keeps the payload; re-run push when the host is up") from error


def _parse(status: int, raw: bytes) -> dict:
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError) as error:
        raise RegistryError("ENVELOPE_INVALID", f"HTTP {status} with a non-JSON body",
                            hint=raw[:200].decode("utf-8", "replace")) from error
    if not isinstance(body, dict):
        raise RegistryError("ENVELOPE_INVALID", "response body is not a JSON object")
    if status == 429:
        raise RegistryError("RATE_LIMITED", "dispatch endpoint is overloaded (HTTP 429)",
                            hint="retry later; telemetry backlogs drain on their own")
    code = body.get("code")
    if not isinstance(code, int):
        raise RegistryError("ENVELOPE_INVALID", f"host envelope lacks an integer code (HTTP {status})",
                            hint=str(body.get("message") or ""))
    if code != 0:
        raise RegistryError("PUSH_FAILED", f"host rejected the payload (code {code})",
                            hint=str(body.get("message") or ""))
    return body


def _require_credentials(config: Config) -> None:
    if not config.token:
        raise RegistryError("TOKEN_NOT_CONFIGURED", "no dispatch token is configured",
                            hint="pass --token or set MF_REGISTRY_TOKEN")
    if not config.endpoint:
        raise RegistryError("ENDPOINT_NOT_CONFIGURED", "no dispatch endpoint is configured",
                            hint="pass --endpoint or set MF_REGISTRY_ENDPOINT")


def _send(config: Config, payload: dict, *, timeout, retries, sleeper) -> dict:
    attempt = 0
    while True:
        try:
            status, raw = _post(config, payload, timeout)
            body = _parse(status, raw)
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            return {"status": str(data.get("status") or "registered"),
                    "traceId": str(body.get("trace_id") or ""),
                    "httpStatus": status}
        except RegistryError as error:
            retryable = error.code in ("PUSH_FAILED", "RATE_LIMITED")
            if attempt >= retries or not retryable:
                raise
            attempt += 1
            sleeper(_RETRY_BACKOFF_SECONDS * attempt)


def publish(config: Config, report: dict, *, timeout=DEFAULT_TIMEOUT_SECONDS,
            retries: int = 0, sleeper=time.sleep) -> dict:
    """Push one snapshot report; returns the host's status."""
    _require_credentials(config)
    return _send(config, build_payload(config, report), timeout=timeout,
                 retries=retries, sleeper=sleeper)


def send_batch(config: Config, batch: dict, *, timeout=DEFAULT_TIMEOUT_SECONDS,
               retries: int = 0, sleeper=time.sleep) -> dict:
    """Push one event batch; returns the host's status."""
    _require_credentials(config)
    return _send(config, build_stream_payload(config, batch), timeout=timeout,
                 retries=retries, sleeper=sleeper)
