"""Command face: five closed commands, three exits, one envelope.

``capabilities``/``diagnostics`` are the discovery face (probe before use);
``export``/``push``/``status`` are the working face. Nothing else is exposed:
expressiveness is deliberately small, and an unimplemented capability must be
absent rather than approximated.
"""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .codes import PROTOCOL, describe_diagnostics
from .collect import REQUIRED_COMMANDS, build_report
from .envelope import dumps, report_digest
from .errors import RegistryError
from .probe import Cli
from .push import (DEFAULT_ENDPOINT, DEFAULT_TIMEOUT_SECONDS, build_payload,
                   build_stream_payload, publish, resolve_config, send_batch)
from .store import Store
from .stream import validate_batch

CAPABILITIES = {
    "capabilities": {"args": [], "flags": [], "ephemeral": "rejected",
                     "resultKeys": ["implementation", "implementationVersion", "commands"]},
    "diagnostics": {"args": [], "flags": [], "ephemeral": "rejected",
                    "resultKeys": ["count", "diagnostics"]},
    "export": {"args": ["project"], "flags": ["--namespace", "--group", "--out", "--stamp"],
               "ephemeral": "required",
               "resultKeys": ["namespace", "group", "source", "project", "assets",
                              "policy", "summary", "diagnostics", "digest"]},
    "push": {"args": ["report"],
             "flags": ["--endpoint", "--token", "--tenant", "--project", "--env-key",
                       "--store", "--force", "--dry-run", "--retries", "--timeout"],
             "ephemeral": "rejected",
             "resultKeys": ["pushed", "namespace", "group", "digest", "status", "endpoint"]},
    "stream": {"args": ["batch?"],
               "flags": ["--replay", "--namespace", "--group", "--endpoint", "--token",
                         "--tenant", "--project", "--env-key", "--store", "--dry-run",
                         "--retries", "--timeout"],
               "ephemeral": "rejected",
               "resultKeys": ["pushed", "acked", "namespace", "group", "contentDigest",
                              "count", "outbox", "endpoint"]},
    "status": {"args": [], "flags": ["--store"], "ephemeral": "rejected",
               "resultKeys": ["root", "snapshots"]},
}

_PUSHED_OK = ("registered", "unchanged", "updated")


def _emit(payload: dict) -> int:
    print(dumps(payload))
    return 0


def _require_ephemeral(args) -> None:
    if not getattr(args, "ephemeral", False):
        raise RegistryError("EPHEMERAL_REQUIRED",
                            f"{args.command} compiles the project; pass --ephemeral",
                            hint="the explicit local boundary keeps deployment state out of play")


def _reject_ephemeral(args) -> None:
    if getattr(args, "ephemeral", False):
        raise RegistryError("EPHEMERAL_REJECTED",
                            f"{args.command} is declarative and does not compile",
                            hint="drop --ephemeral")


def _load_report(path: str) -> dict:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RegistryError("REPORT_INVALID", f"cannot read report: {error}", path=path) from error
    if not isinstance(report, dict):
        raise RegistryError("REPORT_INVALID", "report must be a JSON object", path=path)
    if report.get("protocol") != PROTOCOL:
        raise RegistryError("REPORT_PROTOCOL_MISMATCH",
                            f"expected protocol {PROTOCOL!r}, got {report.get('protocol')!r}",
                            path=path, exit_code=2)
    if report.get("digest") != report_digest(report):
        raise RegistryError("REPORT_DIGEST_MISMATCH",
                            "report digest does not match its content (edited or truncated?)",
                            path=path, hint="re-run export instead of patching the report")
    return report


def _cmd_capabilities(_args) -> int:
    return _emit({"protocol": PROTOCOL, "implementation": "microflow-registry",
                  "implementationVersion": __version__, "commands": CAPABILITIES,
                  "requires": {"cliProtocol": "microflow-cli-v1",
                               "cliCommands": list(REQUIRED_COMMANDS)}})


def _cmd_diagnostics(_args) -> int:
    described = describe_diagnostics()
    return _emit({"protocol": PROTOCOL, "count": described["count"],
                  "diagnostics": described["diagnostics"]})


def _cmd_export(args) -> int:
    _require_ephemeral(args)
    cli = Cli(prefix=args.cli_prefix or None)
    report = build_report(args.project, namespace=args.namespace, group=args.group,
                          cli=cli, stamp=args.stamp)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dumps(report) + "\n", encoding="utf-8")
    return _emit(report)


def _cmd_push(args) -> int:
    _reject_ephemeral(args)
    report = _load_report(args.report)
    store = Store(args.store)
    config = resolve_config(endpoint=args.endpoint, token=args.token, tenant_id=args.tenant,
                            project_id=args.project, env_key=args.env_key)
    if args.dry_run:
        return _emit({"protocol": PROTOCOL, "pushed": False, "dryRun": True,
                      "endpoint": config.endpoint, "payload": build_payload(config, report)})

    unchanged = not store.save(report, force=args.force)
    pushed = store.push_state(report["namespace"], report["group"])
    if (not args.force and unchanged and pushed
            and pushed.get("contentDigest") == report["contentDigest"]
            and pushed.get("status") in _PUSHED_OK):
        return _emit({"protocol": PROTOCOL, "pushed": False, "status": "unchanged",
                      "namespace": report["namespace"], "group": report["group"],
                      "digest": report["digest"], "endpoint": config.endpoint,
                      "source": "client-cache",
                      "note": "same digest already acknowledged; --force to re-send"})

    outcome = publish(config, report, timeout=args.timeout, retries=args.retries)
    store.record_push(report, status=outcome["status"], trace_id=outcome["traceId"])
    return _emit({"protocol": PROTOCOL, "pushed": True, "status": outcome["status"],
                  "namespace": report["namespace"], "group": report["group"],
                  "digest": report["digest"], "endpoint": config.endpoint,
                  "httpStatus": outcome["httpStatus"], "traceId": outcome["traceId"]})


def _cmd_status(args) -> int:
    _reject_ephemeral(args)
    store = Store(args.store)
    return _emit({"protocol": PROTOCOL, "root": str(store.root),
                  "snapshots": store.summary()})


def _addressing(batch: dict, args) -> tuple[str, str]:
    """The batch owns its addressing (it is part of its digest); flags may only confirm it."""
    namespace, group = batch.get("namespace"), batch.get("group")
    for kind, value in (("namespace", namespace), ("group", group)):
        if not isinstance(value, str) or not value:
            raise RegistryError("STREAM_INVALID", f"batch lacks {kind}",
                                path=kind, hint="produce the batch with build_batch()")
    if args.namespace and args.namespace != namespace:
        raise RegistryError("INVALID_ADDRESSING", "batch namespace disagrees with --namespace",
                            path="namespace")
    if args.group and args.group != group:
        raise RegistryError("INVALID_ADDRESSING", "batch group disagrees with --group", path="group")
    return namespace, group


def _cmd_stream(args) -> int:
    _reject_ephemeral(args)
    if not args.batch and not args.replay:
        raise RegistryError("STREAM_INVALID", "stream needs a batch file or --replay")
    if args.batch and args.replay:
        raise RegistryError("STREAM_INVALID", "pass either a batch file or --replay, not both")
    store = Store(args.store)
    config = resolve_config(endpoint=args.endpoint, token=args.token, tenant_id=args.tenant,
                            project_id=args.project, env_key=args.env_key)

    if args.replay:
        if not (args.namespace and args.group):
            raise RegistryError("INVALID_ADDRESSING", "--replay requires --namespace and --group")
        pending = store.pending(args.namespace, args.group)
        if args.dry_run:
            return _emit({"protocol": PROTOCOL, "pushed": False, "dryRun": True,
                          "namespace": args.namespace, "group": args.group,
                          "pending": [batch["contentDigest"] for batch in pending],
                          "outbox": len(pending), "endpoint": config.endpoint})
        acked, frames = 0, 0
        for batch in pending:
            outcome = _push_batch(config, store, batch, args)
            acked += 1
            frames += outcome["count"]
        return _emit({"protocol": PROTOCOL, "pushed": acked > 0, "replay": True,
                      "namespace": args.namespace, "group": args.group,
                      "acked": acked, "frames": frames,
                      "outbox": store.pending_count(args.namespace, args.group),
                      "endpoint": config.endpoint})

    batch = _load_batch(args.batch)
    namespace, group = _addressing(batch, args)
    if args.dry_run:
        return _emit({"protocol": PROTOCOL, "pushed": False, "dryRun": True,
                      "endpoint": config.endpoint,
                      "payload": build_stream_payload(config, batch)})

    state = store.stream_state(namespace, group)
    if (state and state.get("contentDigest") == batch["contentDigest"]
            and state.get("status") in _PUSHED_OK
            and not store.pending_count(namespace, group)):
        return _emit({"protocol": PROTOCOL, "pushed": False, "status": "unchanged",
                      "namespace": namespace, "group": group,
                      "contentDigest": batch["contentDigest"], "count": batch["count"],
                      "endpoint": config.endpoint, "source": "client-cache",
                      "note": "same batch digest already acknowledged; --dry-run to inspect"})

    store.enqueue(batch)                       # durable before the network call
    outcome = _push_batch(config, store, batch, args)
    return _emit({"protocol": PROTOCOL, "pushed": True, "status": outcome["status"],
                  "namespace": namespace, "group": group,
                  "contentDigest": batch["contentDigest"], "count": outcome["count"],
                  "acked": 1, "outbox": store.pending_count(namespace, group),
                  "endpoint": config.endpoint, "httpStatus": outcome["httpStatus"],
                  "traceId": outcome["traceId"]})


def _push_batch(config, store, batch: dict, args) -> dict:
    outcome = send_batch(config, batch, timeout=args.timeout, retries=args.retries)
    store.ack(batch)
    store.record_stream(batch, status=outcome["status"], trace_id=outcome["traceId"])
    return {"status": outcome["status"], "count": batch["count"],
            "httpStatus": outcome.get("httpStatus"), "traceId": outcome.get("traceId")}


def _load_batch(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RegistryError("STREAM_INVALID", f"cannot read batch: {error}", path=path) from error
    return validate_batch(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microflow-registry",
                                     description="Publish MicroFlow snapshot metadata, idempotent by digest")
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("capabilities", "diagnostics", "status"):
        sub = commands.add_parser(name)
        sub.add_argument("--ephemeral", action="store_true")
        if name == "status":
            sub.add_argument("--store", default=None, help="snapshot store root")

    export = commands.add_parser("export", help="Project a project file into a deterministic report")
    export.add_argument("project")
    export.add_argument("--namespace", required=True, help="business domain (Nacos namespace)")
    export.add_argument("--group", required=True, help="environment key (Nacos group)")
    export.add_argument("--out", default=None, help="also write the report to this file")
    export.add_argument("--stamp", action="store_true",
                        help="add meta.generatedAt (excluded from the digest)")
    export.add_argument("--cli", dest="cli_prefix", default=None,
                        help="override the CLI entry (shell-free, space separated)")
    export.add_argument("--ephemeral", action="store_true")

    push = commands.add_parser("push", help="Register a report through the host dispatch envelope")
    push.add_argument("report")
    push.add_argument("--endpoint", default=None,
                      help=f"dispatch endpoint (default: env or {DEFAULT_ENDPOINT})")
    push.add_argument("--token", default=None, help="dispatch token (default: MF_REGISTRY_TOKEN)")
    push.add_argument("--tenant", default=None)
    push.add_argument("--project", default=None)
    push.add_argument("--env-key", dest="env_key", default=None)
    push.add_argument("--store", default=None, help="snapshot store root")
    push.add_argument("--force", action="store_true", help="re-send even if unchanged")
    push.add_argument("--dry-run", dest="dry_run", action="store_true",
                      help="print the payload without any network call")
    push.add_argument("--retries", type=int, default=0, help="bounded retries (default 0)")
    push.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    push.add_argument("--ephemeral", action="store_true")

    stream = commands.add_parser("stream", help="Register an event batch (outbox-backed, at-least-once)")
    stream.add_argument("batch", nargs="?", default=None, help="batch JSON file")
    stream.add_argument("--replay", action="store_true", help="drain the local outbox instead")
    stream.add_argument("--namespace", default=None)
    stream.add_argument("--group", default=None)
    stream.add_argument("--endpoint", default=None,
                        help=f"dispatch endpoint (default: env or {DEFAULT_ENDPOINT})")
    stream.add_argument("--token", default=None, help="dispatch token (default: MF_REGISTRY_TOKEN)")
    stream.add_argument("--tenant", default=None)
    stream.add_argument("--project", default=None)
    stream.add_argument("--env-key", dest="env_key", default=None)
    stream.add_argument("--store", default=None, help="snapshot store root")
    stream.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="print the payload without any network call")
    stream.add_argument("--retries", type=int, default=0)
    stream.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    stream.add_argument("--ephemeral", action="store_true")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if getattr(args, "cli_prefix", None):
        args.cli_prefix = args.cli_prefix.split()
    try:
        handler = {"capabilities": _cmd_capabilities, "diagnostics": _cmd_diagnostics,
                   "export": _cmd_export, "push": _cmd_push, "status": _cmd_status,
                   "stream": _cmd_stream}[args.command]
        return handler(args)
    except RegistryError as error:
        print(dumps({"protocol": PROTOCOL, **error.envelope()}))
        return error.exit_code
    except Exception as error:  # noqa: BLE001 - boundary: no traceback on stdout
        failure = RegistryError("UNEXPECTED_FAILURE", f"{type(error).__name__}: {error}")
        print(dumps({"protocol": PROTOCOL, **failure.envelope()}))
        return failure.exit_code


if __name__ == "__main__":
    sys.exit(main())
