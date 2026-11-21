"""宿主参考实现的 SQLite 持久化（协议验证介质；生产介质归宿主演进）。"""
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    permissions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_roles (
    user_id INTEGER NOT NULL REFERENCES users(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (user_id, role_id)
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    role_id INTEGER REFERENCES roles(id),
    PRIMARY KEY (user_id, tenant_id)
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);
CREATE TABLE IF NOT EXISTS project_members (
    user_id INTEGER NOT NULL REFERENCES users(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    role_id INTEGER REFERENCES roles(id),
    PRIMARY KEY (user_id, project_id)
);
CREATE TABLE IF NOT EXISTS envs (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL,
    PRIMARY KEY (project_id, key)
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    actor TEXT,
    tenant_id INTEGER,
    project_id INTEGER,
    env_key TEXT
);
CREATE TABLE IF NOT EXISTS telemetry (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    event TEXT NOT NULL,
    release_id TEXT,
    environment TEXT,
    page_definition_id TEXT,
    page_instance_id TEXT,
    locale TEXT,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_event_at ON telemetry(event, at);
"""

SESSION_TTL_HOURS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HostDatabase:
    """单机 SQLite；连接跨线程可用，全部方法经锁串行化（与 DeliveryStore 同纪律）。"""

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

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def transaction(self) -> "HostTransaction":
        return HostTransaction(self)

    # ---- 会话 ----

    def create_session(self, user_id: int) -> tuple[str, str]:
        token = secrets.token_hex(32)
        created = _now()
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat(timespec="seconds")
        self.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                     (token, user_id, created, expires))
        return token, expires

    def session_user(self, token: str) -> sqlite3.Row | None:
        row = self.query_one(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.expires_at > ?", (token, _now()))
        return row

    # ---- 审计 ----

    def audit_append(self, actor: str, action: str, target: str, detail: str | None = None) -> None:
        self.execute("INSERT INTO audit (at, actor, action, target, detail) VALUES (?,?,?,?,?)",
                     (_now(), actor, action, target, detail))


class HostTransaction:
    """多写原子收口（与控制面事务化纪律同构：一批治理变更要么全落要么全不落）。"""

    def __init__(self, db: HostDatabase):
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db._lock.acquire()
        return self._db._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._db._conn.commit()
            else:
                self._db._conn.rollback()
        finally:
            self._db._lock.release()
