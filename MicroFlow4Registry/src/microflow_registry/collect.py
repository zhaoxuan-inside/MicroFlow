"""Read-only projection: CLI facts in, one deterministic report out.

Nothing here re-derives framework semantics. Operator facts come from
``microflow operators``, the project identity from ``microflow check``, and
policy comes as digests of the CLI's own schema/defaults/merge projections.
Effective policy is *not* merged here: that would create a second truth.
"""
import datetime
import os
import re
from pathlib import Path

from .envelope import bytes_digest, digest, report_digest
from .errors import RegistryError
from .probe import Cli
from .codes import PROTOCOL

REQUIRED_COMMANDS = ("check", "operators", "policy-schema")
POLICY_PROTOCOL = "microflow-policy-schema-v1"
_ADDRESSING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

EFFECTIVE_POLICY_REASON = ("CLI exposes policy defaults and merge rules only; "
                           "merging layers here would create a second truth")
EFFECTIVE_POLICY_HINT = ("add a read-only effective-policy command to the kernel, "
                         "then upgrade this projection")


def check_addressing(kind: str, value: str) -> str:
    """Nacos-style namespace/group keys: short, safe, non-empty."""
    if not isinstance(value, str) or not _ADDRESSING.match(value):
        raise RegistryError("INVALID_ADDRESSING",
                            f"{kind} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}",
                            path=kind, hint=f"got {value!r}")
    return value


def _require_keys(payload: dict, command: str, keys) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise RegistryError("CLI_CONTRACT_MISMATCH",
                            f"{command} envelope lacks {missing}",
                            hint="the CLI and this projection disagree about resultKeys")


def _relpath(path: str, base: Path) -> str:
    try:
        relative = os.path.relpath(path, base)
    except ValueError:                      # different drives / unresolvable
        relative = os.path.basename(path)
    return relative.replace(os.sep, "/")


def _source_digest(path: str) -> str:
    try:
        return bytes_digest(Path(path).read_bytes())
    except OSError as error:
        raise RegistryError("CLI_FAILED",
                            "operator source file reported by the CLI is unreadable",
                            path=path, hint=str(error)) from error


def _split_ref(ref: str) -> tuple[str, str]:
    name, separator, version = ref.rpartition("@")
    if not separator or not name or not version:
        raise RegistryError("INVALID_ADDRESSING", f"operator ref is not name@version: {ref!r}",
                            path="assets")
    return name, version


def _asset(operator: dict, project_dir: Path) -> dict:
    ref = operator.get("ref")
    if not isinstance(ref, str):
        raise RegistryError("CLI_CONTRACT_MISMATCH", "operators entry lacks a string ref")
    name, version = _split_ref(ref)
    source_file = operator.get("sourceFile") or ""
    asset = {
        "kind": "operator",
        "dataId": ref,
        "name": name,
        "version": version,
        "ref": ref,
        "description": operator.get("description") or "",
        "inputSchema": operator.get("inputSchema") or "",
        "outputSchema": operator.get("outputSchema") or "",
        "capabilities": operator.get("capabilities") or {},
        "fallbackCapabilities": operator.get("fallbackCapabilities") or {},
        "declaredPolicy": operator.get("defaultPolicy") or {},
        "source": {"path": _relpath(source_file, project_dir), "sha256": _source_digest(source_file)},
        "staticReferences": int(operator.get("staticReferences") or 0),
        "referencingFlows": sorted(operator.get("referencingFlows") or []),
    }
    asset["digest"] = digest(asset)
    return asset


def content_digest(report: dict) -> str:
    """Path-independent identity of everything that matters.

    The framework's ``releaseId`` hashes a manifest whose source map is keyed by
    absolute file paths, so it changes with the checkout directory. The report
    keeps both: ``releaseId`` stays the framework's truth, ``contentDigest`` is
    the portable key used for cross-machine idempotency.
    """
    return digest({
        "namespace": report["namespace"],
        "group": report["group"],
        "project": {key: report["project"][key] for key in ("digest", "durability", "flows")},
        "assets": [{"dataId": asset["dataId"], "digest": asset["digest"]}
                   for asset in report["assets"]],
        "policy": {key: report["policy"][key]
                   for key in ("schemaDigest", "defaultsDigest", "mergeDigest")},
    })


def build_report(project, *, namespace: str, group: str, cli=None, stamp: bool = False) -> dict:
    """Project a project file into a ``microflow-registry-v1`` report."""
    cli = cli or Cli()
    namespace = check_addressing("namespace", namespace)
    group = check_addressing("group", group)
    project_path = Path(project)
    project_dir = project_path.resolve().parent

    # 1. Conditional assembly: probe before use.
    capabilities = cli.require(["capabilities"])
    _require_keys(capabilities, "capabilities", ("commands", "implementation", "implementationVersion"))
    commands = sorted(capabilities["commands"])
    missing = [name for name in REQUIRED_COMMANDS if name not in capabilities["commands"]]
    if missing:
        raise RegistryError("UNSUPPORTED_COMMAND",
                            f"installed CLI lacks required commands: {missing}",
                            hint=f"available: {commands}")

    # 2. Static gate: zero diagnostics before anything is registered.
    gate = cli.call(["check", str(project_path), "--ephemeral"])
    if gate.code != 0:
        diagnostic = gate.payload.get("diagnostic") or {}
        raise RegistryError("CLI_FAILED",
                            f"{diagnostic.get('error_code', 'unknown')}: "
                            f"{diagnostic.get('message', 'check rejected the project')}",
                            path=str(diagnostic.get("path") or project_path),
                            hint=str(diagnostic.get("hint") or ""))
    _require_keys(gate.payload, "check", ("releaseId", "flows", "diagnostics", "durability"))
    diagnostics = gate.payload["diagnostics"]
    if diagnostics:
        codes = sorted({str(entry.get("error_code") or entry.get("code") or "unknown")
                        for entry in diagnostics})
        raise RegistryError("PROJECT_CHECK_FAILED",
                            f"check reported {len(diagnostics)} diagnostic(s): {codes}",
                            path=str(project_path),
                            hint="fix the project until check is 0 diagnostics", exit_code=1)

    # 3. Facts, read once, projected without re-deriving.
    operators = cli.require(["operators", str(project_path), "--ephemeral"])
    _require_keys(operators, "operators", ("releaseId", "operators"))
    policy = cli.require(["policy-schema"], protocols=(POLICY_PROTOCOL,))
    _require_keys(policy, "policy-schema", ("schema", "defaults", "merge"))

    release_id = gate.payload["releaseId"]
    if operators["releaseId"] != release_id:
        raise RegistryError("RELEASE_MISMATCH",
                            "check and operators disagree about releaseId",
                            hint=f"{release_id} != {operators['releaseId']}")

    assets = sorted((_asset(operator, project_dir) for operator in operators["operators"]),
                    key=lambda asset: asset["dataId"])

    report = {
        "protocol": PROTOCOL,
        "namespace": namespace,
        "group": group,
        "source": {
            "implementation": capabilities["implementation"],
            "implementationVersion": capabilities["implementationVersion"],
            "cliProtocol": gate.payload.get("protocol", ""),
            "cliEntry": cli.entry,
            "commands": commands,
        },
        "project": {
            "digest": bytes_digest(project_path.read_bytes()),
            "releaseId": release_id,
            "durability": gate.payload["durability"],
            "flows": sorted(gate.payload["flows"]),
        },
        "assets": assets,
        "policy": {
            "protocol": policy["protocol"],
            "schemaDigest": digest(policy["schema"]),
            "defaultsDigest": digest(policy["defaults"]),
            "mergeDigest": digest(policy["merge"]),
            "effective": "unavailable",
            "reason": EFFECTIVE_POLICY_REASON,
            "hint": EFFECTIVE_POLICY_HINT,
        },
        "summary": {"assets": len(assets), "flows": len(gate.payload["flows"]),
                    "diagnostics": 0},
        "diagnostics": [],
    }
    if stamp:
        report["meta"] = {"generatedAt": datetime.datetime.now(datetime.UTC)
                         .replace(microsecond=0).isoformat().replace("+00:00", "Z")}
    report["contentDigest"] = content_digest(report)
    report["digest"] = report_digest(report)
    return report
