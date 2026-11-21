"""内容寻址产物仓库 + 环境指针 + 发布门禁（SQLite 单机起步）。

语义对齐：
- 产物/证据 SHA-256 内容寻址（与框架 T12 releases.publish、宿主 config_hash 同语义）；
- 环境链 dev→test→staging→online 不可跳过：守卫读"该产物在上一环境的通过记录"
  （per-version 历史证据，对齐编排控制面 E2E 门禁语义），回滚 = 旧产物重走 promote、
  守卫照常；
- staging/online 强制第二人审批，同人禁审是存储层硬校验（与编排审批纪律同构）；
- 审计追加保留（append-only），不提供删除路径。

时间戳只来自真实事件（登记/推进发生时刻），不参与门禁判定。单机仓库：连接跨线程
可用（REST 服务在自身线程处理请求），全部方法经锁串行化。
"""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DeliveryError, GateRejected

ENVS = ("dev", "test", "staging", "online")
PROTECTED_ENVS = ("staging", "online")
ARTIFACT_KINDS = ("web_bundle", "backend_service", "model_snapshot")
MAX_EVIDENCE_BYTES = 1_000_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    blob_digest TEXT NOT NULL,
    blob_size INTEGER NOT NULL,
    build_inputs TEXT,
    spec_digest TEXT NOT NULL,
    spec_coverage TEXT NOT NULL,
    check_report TEXT NOT NULL,
    verify_report TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    env TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    approver TEXT,
    promoted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pointers (
    env TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    approver TEXT,
    promoted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_evidence(path: Path, name: str) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeliveryError("FILE_UNAVAILABLE", f"Cannot read {name} evidence", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise DeliveryError("EVIDENCE_MALFORMED", f"{name} evidence is not valid JSON", str(exc)) from exc
    if not isinstance(raw, dict):
        raise DeliveryError("EVIDENCE_MALFORMED", f"{name} evidence must be a JSON object", str(path))
    if len(_canonical(raw)) > MAX_EVIDENCE_BYTES:
        raise DeliveryError("EVIDENCE_LIMIT", f"{name} evidence exceeds the {MAX_EVIDENCE_BYTES} byte budget")
    return raw


def _require_envelope(report: dict, envelope: str, *, command: str | None, name: str) -> None:
    if report.get("envelope") != envelope and report.get("protocol") != envelope:
        raise DeliveryError("EVIDENCE_MALFORMED", f"{name} evidence envelope must be {envelope!r}",
                            str(report.get("envelope") or report.get("protocol")))
    if command is not None and report.get("command") != command:
        raise DeliveryError("EVIDENCE_MALFORMED", f"{name} evidence must come from the {command!r} command",
                            str(report.get("command")))


def _artifact_id(kind: str, blob_digest: str, build_inputs: dict | None, evidence: dict) -> str:
    manifest = {
        "kind": kind,
        "blob_digest": blob_digest,
        "build_inputs": build_inputs,
        "spec_digest": evidence["spec_digest"],
        "spec_coverage_digest": evidence["spec_coverage_digest"],
        "check_report_digest": evidence["check_report_digest"],
        "verify_report_digest": evidence["verify_report_digest"],
    }
    return f"sha256:{_sha256_hex(_canonical(manifest).encode('utf-8'))}"


class DeliveryStore:
    """单机 SQLite 仓库。门禁在存储层执行——CLI 与 REST 服务共享同一判定源。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- 登记 ----

    def register_artifact(self, *, kind: str, blob: bytes, spec_coverage_path: Path,
                          check_report_path: Path, verify_report_path: Path,
                          build_inputs_path: Path | None, registered_by: str) -> dict:
        if kind not in ARTIFACT_KINDS:
            raise DeliveryError("INVALID_ARTIFACT_KIND",
                                f"kind must be one of {', '.join(ARTIFACT_KINDS)}", kind)
        if not registered_by.strip():
            raise DeliveryError("INVALID_ACTOR", "registered_by must be a nonempty name")
        spec_coverage = _load_evidence(spec_coverage_path, "spec-coverage")
        check_report = _load_evidence(check_report_path, "check")
        verify_report = _load_evidence(verify_report_path, "verify")
        _require_envelope(spec_coverage, "microflow-spec-v1", command="coverage", name="spec-coverage")
        _require_envelope(check_report, "microflow-cli-v1", command=None, name="check")
        _require_envelope(verify_report, "microflow-verify-v1", command=None, name="verify")
        spec_digest = spec_coverage.get("spec", {}).get("digest")
        if not isinstance(spec_digest, str) or not spec_digest.startswith("sha256:"):
            raise DeliveryError("EVIDENCE_MALFORMED",
                                "spec-coverage evidence must bind a spec digest (spec.digest)", str(spec_digest))
        evidence = {
            "spec_digest": spec_digest,
            "spec_coverage_digest": f"sha256:{_sha256_hex(_canonical(spec_coverage).encode('utf-8'))}",
            "check_report_digest": f"sha256:{_sha256_hex(_canonical(check_report).encode('utf-8'))}",
            "verify_report_digest": f"sha256:{_sha256_hex(_canonical(verify_report).encode('utf-8'))}",
        }
        build_inputs = _load_evidence(build_inputs_path, "build-inputs") if build_inputs_path else None
        blob_digest = f"sha256:{_sha256_hex(blob)}"
        artifact_id = _artifact_id(kind, blob_digest, build_inputs, evidence)
        registered_at = _now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
            if existing is None:
                # 同一登记内容重复登记是幂等操作（内容寻址语义）。
                self._conn.execute(
                    "INSERT INTO artifacts (artifact_id, kind, blob_digest, blob_size, build_inputs,"
                    " spec_digest, spec_coverage, check_report, verify_report, registered_by, registered_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (artifact_id, kind, blob_digest, len(blob),
                     _canonical(build_inputs) if build_inputs is not None else None,
                     spec_digest, _canonical(spec_coverage), _canonical(check_report),
                     _canonical(verify_report), registered_by, registered_at))
                self._audit_locked("register", {"artifact_id": artifact_id, "kind": kind,
                                                "blob_digest": blob_digest, "by": registered_by})
                self._conn.commit()
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    # ---- 读取 ----

    def get_artifact(self, artifact_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        return self._artifact_row(row) if row else None

    def list_artifacts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM artifacts ORDER BY registered_at, artifact_id").fetchall()
        return [self._artifact_row(row) for row in rows]

    def _artifact_row(self, row: sqlite3.Row) -> dict:
        build_inputs = json.loads(row["build_inputs"]) if row["build_inputs"] else None
        return {"artifactId": row["artifact_id"], "kind": row["kind"],
                "blobDigest": row["blob_digest"], "blobSize": row["blob_size"],
                "buildInputs": build_inputs, "specDigest": row["spec_digest"],
                "registeredBy": row["registered_by"], "registeredAt": row["registered_at"]}

    def pointer(self, env: str) -> dict | None:
        with self._lock:
            return self._pointer_locked(env)

    def pointers(self) -> list[dict]:
        out = []
        for env in ENVS:
            pointer = self.pointer(env)
            if pointer is not None:
                out.append(pointer)
        return out

    def audit(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [{"seq": row["seq"], "at": row["at"], "event": row["event"],
                 **json.loads(row["payload"])} for row in rows]

    # ---- 推进（门禁在此执行） ----

    def promote(self, artifact_id: str, env: str, *, actor: str, approver: str | None = None) -> dict:
        if env not in ENVS:
            raise DeliveryError("UNKNOWN_ENV", f"env must be one of {', '.join(ENVS)}", env)
        if not actor.strip():
            raise DeliveryError("INVALID_ACTOR", "actor must be a nonempty name")
        with self._lock:
            row = self._conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
            if row is None:
                raise DeliveryError("UNKNOWN_ARTIFACT", "Artifact is not registered in this store", artifact_id)

            reasons: list[dict[str, str]] = []
            coverage = json.loads(row["spec_coverage"])
            if coverage.get("ok") is not True:
                summary = coverage.get("summary", {})
                reasons.append({"gate": "spec-coverage",
                                "reason": f"coverage not green (uncovered={summary.get('uncovered')}, "
                                          f"orphans={len(coverage.get('orphans', []))})"})
            check_report = json.loads(row["check_report"])
            diagnostics = check_report.get("diagnostics")
            if not isinstance(diagnostics, list) or len(diagnostics) != 0:
                reasons.append({"gate": "check",
                                "reason": f"check report carries "
                                          f"{len(diagnostics) if isinstance(diagnostics, list) else 'no'} diagnostics"})
            verify = json.loads(row["verify_report"])
            if verify.get("verdict") != "pass":
                reasons.append({"gate": "verify", "reason": f"verify verdict is {verify.get('verdict')!r}"})
            index = ENVS.index(env)
            if index > 0:
                previous = ENVS[index - 1]
                passed = self._conn.execute(
                    "SELECT 1 FROM promotions WHERE env = ? AND artifact_id = ? LIMIT 1",
                    (previous, artifact_id)).fetchone()
                if passed is None:
                    reasons.append({"gate": "env-order",
                                    "reason": f"artifact has no promotion record in {previous}; "
                                              f"{'→'.join(ENVS)} cannot be skipped"})
            if env in PROTECTED_ENVS:
                if not approver or not approver.strip():
                    reasons.append({"gate": "approval", "reason": f"{env} requires a second-person approver"})
                elif approver == actor:
                    reasons.append({"gate": "approval", "reason": "approver must differ from the actor (同人禁审)"})
            if reasons:
                raise GateRejected(reasons)

            current_pointer = self._pointer_locked(env)
            rollback = current_pointer is not None and current_pointer["artifactId"] != artifact_id
            promoted_at = _now()
            self._conn.execute(
                "INSERT INTO promotions (env, artifact_id, promoted_by, approver, promoted_at)"
                " VALUES (?,?,?,?,?)", (env, artifact_id, actor, approver, promoted_at))
            self._conn.execute(
                "INSERT INTO pointers (env, artifact_id, promoted_by, approver, promoted_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(env) DO UPDATE SET artifact_id=excluded.artifact_id,"
                " promoted_by=excluded.promoted_by, approver=excluded.approver,"
                " promoted_at=excluded.promoted_at",
                (env, artifact_id, actor, approver, promoted_at))
            event = "rollback" if rollback else "promote"
            self._audit_locked(event, {"env": env, "artifact_id": artifact_id, "by": actor,
                                       "approver": approver,
                                       "previous": current_pointer["artifactId"] if current_pointer else None})
            self._conn.commit()
            pointer = self._pointer_locked(env)
        assert pointer is not None
        return {**pointer, "event": event, "rollback": rollback}

    def _pointer_locked(self, env: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM pointers WHERE env = ?", (env,)).fetchone()
        if row is None:
            return None
        return {"env": row["env"], "artifactId": row["artifact_id"], "promotedBy": row["promoted_by"],
                "approver": row["approver"], "promotedAt": row["promoted_at"]}

    def _audit_locked(self, event: str, payload: dict) -> None:
        self._conn.execute("INSERT INTO audit (at, event, payload) VALUES (?,?,?)",
                           (_now(), event, _canonical(payload)))
