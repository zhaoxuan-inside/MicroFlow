"""Local snapshot store: the Nacos-style client cache, minus the daemon.

A snapshot is written before any network call, so a failed push never loses
the thing that was about to be pushed. Writes are atomic (temp file plus
``os.replace``) because a half-written snapshot would be worse than none.
"""
import json
import os
import re
import time
from pathlib import Path

from .envelope import dumps
from .errors import RegistryError

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def default_root() -> Path:
    base = os.getenv("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "microflow-registry"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else default_root()

    # ---- paths -----------------------------------------------------------

    def _dir(self, namespace: str, group: str) -> Path:
        for kind, value in (("namespace", namespace), ("group", group)):
            if not isinstance(value, str) or not _SAFE.match(value):
                raise RegistryError("INVALID_ADDRESSING",
                                    f"{kind} is not a safe directory key", path=kind)
        return self.root / "snapshots" / namespace / group

    def report_path(self, namespace: str, group: str) -> Path:
        return self._dir(namespace, group) / "report.json"

    def push_path(self, namespace: str, group: str) -> Path:
        return self._dir(namespace, group) / "push.json"

    def outbox_dir(self, namespace: str, group: str) -> Path:
        return self._dir(namespace, group) / "outbox"

    def stream_path(self, namespace: str, group: str) -> Path:
        return self._dir(namespace, group) / "stream.json"

    # ---- io --------------------------------------------------------------

    @staticmethod
    def _read(path: Path, expected: str) -> dict | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RegistryError("STORE_CORRUPT", f"cannot read {path.name}: {error}",
                                path=str(path)) from error
        if not isinstance(value, dict):
            raise RegistryError("STORE_CORRUPT", f"{path.name} is not a JSON object",
                                path=str(path))
        return value

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(dumps(value) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    # ---- snapshots -------------------------------------------------------

    def load(self, namespace: str, group: str) -> dict | None:
        return self._read(self.report_path(namespace, group), "report")

    def push_state(self, namespace: str, group: str) -> dict | None:
        return self._read(self.push_path(namespace, group), "push")

    def conflicts(self, report: dict) -> list:
        """Assets pinned to the same id with different content (non-determinism)."""
        previous = self.load(report["namespace"], report["group"])
        if not previous:
            return []
        known = {asset["dataId"]: asset["digest"] for asset in previous.get("assets") or []}
        return [{"dataId": asset["dataId"], "previous": known[asset["dataId"]],
                 "current": asset["digest"]}
                for asset in report.get("assets") or []
                if asset["dataId"] in known and known[asset["dataId"]] != asset["digest"]]

    def save(self, report: dict, *, force: bool = False) -> bool:
        """Persist a snapshot; returns False when it was already identical."""
        conflicts = self.conflicts(report)
        if conflicts and not force:
            ids = sorted(entry["dataId"] for entry in conflicts)
            raise RegistryError(
                "REGISTRY_DIGEST_CONFLICT",
                f"same asset id with different content: {ids}",
                path=str(self.report_path(report["namespace"], report["group"])),
                hint="bump the asset version, or --force after human review",
                exit_code=1)
        previous = self.load(report["namespace"], report["group"])
        if previous and previous.get("digest") == report.get("digest") and not force:
            return False
        self._write(self.report_path(report["namespace"], report["group"]), report)
        return True

    def record_push(self, report: dict, *, status: str, trace_id: str = "") -> dict:
        state = {"namespace": report["namespace"], "group": report["group"],
                 "digest": report["digest"], "contentDigest": report.get("contentDigest", ""),
                 "status": status, "traceId": trace_id, "pushedAt": _timestamp()}
        self._write(self.push_path(report["namespace"], report["group"]), state)
        return state

    # ---- event outbox (at-least-once transport) --------------------------

    def enqueue(self, batch: dict) -> bool:
        """Persist one batch before any network call; returns False if already queued."""
        directory = self.outbox_dir(batch["namespace"], batch["group"])
        digest_value = batch["contentDigest"]
        if directory.is_dir() and any(directory.glob(f"*-{digest_value}.json")):
            return False
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns():020d}-{digest_value}.json"
        self._write(directory / name, batch)
        return True

    def pending(self, namespace: str, group: str) -> list:
        directory = self.outbox_dir(namespace, group)
        if not directory.is_dir():
            return []
        batches = [self._read(path, "batch") for path in sorted(directory.glob("*.json"))]
        return [batch for batch in batches if batch]

    def pending_count(self, namespace: str, group: str) -> int:
        directory = self.outbox_dir(namespace, group)
        return len(list(directory.glob("*.json"))) if directory.is_dir() else 0

    def ack(self, batch: dict) -> None:
        directory = self.outbox_dir(batch["namespace"], batch["group"])
        if not directory.is_dir():
            return
        for path in directory.glob(f"*-{batch['contentDigest']}.json"):
            path.unlink(missing_ok=True)

    def stream_state(self, namespace: str, group: str) -> dict | None:
        return self._read(self.stream_path(namespace, group), "stream")

    def record_stream(self, batch: dict, *, status: str, trace_id: str = "") -> dict:
        state = {"namespace": batch["namespace"], "group": batch["group"],
                 "contentDigest": batch["contentDigest"], "count": batch["count"],
                 "status": status, "traceId": trace_id, "flushedAt": _timestamp()}
        self._write(self.stream_path(batch["namespace"], batch["group"]), state)
        return state

    # ---- read face (Actuator-style, no probing) --------------------------

    def summary(self) -> list:
        rows = []
        base = self.root / "snapshots"
        if not base.is_dir():
            return rows
        for group_dir in sorted(path for path in base.glob("*/*") if path.is_dir()):
            namespace, group = group_dir.parent.name, group_dir.name
            report = self._read(group_dir / "report.json", "report") or {}
            pushed = self.push_state(namespace, group) or {}
            stream = self.stream_state(namespace, group) or {}
            rows.append({
                "namespace": namespace,
                "group": group,
                "digest": report.get("digest", ""),
                "contentDigest": report.get("contentDigest", ""),
                "releaseId": (report.get("project") or {}).get("releaseId", ""),
                "assets": len(report.get("assets") or []),
                "lastPush": {"status": pushed.get("status", "never"),
                             "digest": pushed.get("digest", ""),
                             "contentDigest": pushed.get("contentDigest", ""),
                             "pushedAt": pushed.get("pushedAt", "")},
                "lastStream": {"status": stream.get("status", "never"),
                               "contentDigest": stream.get("contentDigest", ""),
                               "count": stream.get("count", 0),
                               "flushedAt": stream.get("flushedAt", "")},
                "outbox": self.pending_count(namespace, group),
                "inSync": bool(report.get("contentDigest"))
                          and report.get("contentDigest") == pushed.get("contentDigest"),
            })
        return rows
