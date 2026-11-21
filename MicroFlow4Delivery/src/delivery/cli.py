"""结构化命令面：register / list / show / promote / pointers / audit。

契约（与 CLI 八条兼容契约同纪律）：统一信封 `microflow-delivery-v1`；退出码
0 肯定 / 1 门禁否定（GateRejected）/ 2 请求失败（DeliveryError）；时间戳来自
真实事件，决策字段确定性。
"""
import argparse
import json
import sys
from pathlib import Path

from .errors import DeliveryError, GateRejected
from .store import ARTIFACT_KINDS, ENVS, DeliveryStore

DEFAULT_STORE = Path("delivery-store.sqlite3")


def _store(path: str | None) -> DeliveryStore:
    return DeliveryStore(Path(path) if path else DEFAULT_STORE)


def _load_blob(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DeliveryError("FILE_UNAVAILABLE", "Cannot read the artifact file", str(exc)) from exc


def _run(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(prog="delivery")
    parser.add_argument("--store", default=None, help="SQLite store path (default ./delivery-store.sqlite3)")
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="Register a build artifact with its evidence")
    register.add_argument("--kind", required=True, choices=ARTIFACT_KINDS)
    register.add_argument("--artifact", required=True, type=Path)
    register.add_argument("--spec-coverage", required=True, type=Path)
    register.add_argument("--check-report", required=True, type=Path)
    register.add_argument("--verify-report", required=True, type=Path)
    register.add_argument("--build-inputs", type=Path, default=None)
    register.add_argument("--by", required=True, help="Registrant name (audit identity)")

    commands.add_parser("list", help="List registered artifacts")
    show = commands.add_parser("show", help="Show one artifact record")
    show.add_argument("artifact_id")

    promote = commands.add_parser("promote", help="Promote an artifact to an environment (gated)")
    promote.add_argument("artifact_id")
    promote.add_argument("env", choices=ENVS)
    promote.add_argument("--actor", required=True, help="Promoter name (audit identity)")
    promote.add_argument("--approver", default=None, help="Second-person approver (staging/online)")

    commands.add_parser("pointers", help="Show the environment pointer table")
    audit = commands.add_parser("audit", help="Append-only audit trail")
    audit.add_argument("--limit", type=int, default=100)

    args = parser.parse_args(argv)
    store = _store(args.store)
    try:
        if args.command == "register":
            artifact = store.register_artifact(
                kind=args.kind, blob=_load_blob(args.artifact),
                spec_coverage_path=args.spec_coverage, check_report_path=args.check_report,
                verify_report_path=args.verify_report, build_inputs_path=args.build_inputs,
                registered_by=args.by)
            return {"command": "register", "ok": True, "artifact": artifact}
        if args.command == "list":
            return {"command": "list", "ok": True, "artifacts": store.list_artifacts()}
        if args.command == "show":
            artifact = store.get_artifact(args.artifact_id)
            if artifact is None:
                raise DeliveryError("UNKNOWN_ARTIFACT", "Artifact is not registered in this store", args.artifact_id)
            return {"command": "show", "ok": True, "artifact": artifact}
        if args.command == "promote":
            pointer = store.promote(args.artifact_id, args.env, actor=args.actor, approver=args.approver)
            return {"command": "promote", "ok": True, "pointer": pointer}
        if args.command == "pointers":
            return {"command": "pointers", "ok": True, "pointers": store.pointers()}
        if args.command == "audit":
            return {"command": "audit", "ok": True, "events": store.audit(limit=args.limit)}
        raise DeliveryError("UNKNOWN_COMMAND", f"Unknown command {args.command!r}")
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    try:
        result = _run(list(sys.argv[1:] if argv is None else argv))
        exit_code = 0
    except GateRejected as exc:
        result = exc.envelope()
        exit_code = 1
    except DeliveryError as exc:
        result = exc.envelope()
        exit_code = 2
    print(json.dumps({"protocol": "microflow-delivery-v1", "exit": exit_code, **result},
                     ensure_ascii=True, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
