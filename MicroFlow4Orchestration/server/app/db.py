"""orch_control 数据库：连接池 + Schema 自动创建 + 内置管理员引导。"""
import asyncio
import os
import secrets
import hashlib
import uuid
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.getenv(
    "ORCH_DATABASE_URL",
    "postgresql://opc:opchub_secret@127.0.0.1:5432/orch_control",
)
_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  nickname TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  email TEXT NOT NULL,
  nickname TEXT NOT NULL,
  role TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS operators (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  domain TEXT NOT NULL DEFAULT 'custom',
  description TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'platform',
  source_env TEXT NOT NULL DEFAULT '',
  current_version TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS operator_versions (
  operator_name TEXT NOT NULL REFERENCES operators(name) ON DELETE CASCADE,
  version TEXT NOT NULL,
  code TEXT NOT NULL DEFAULT '',
  entry_function TEXT NOT NULL DEFAULT 'action_entry',
  changelog TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'DRAFT',
  unit_test TEXT,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (operator_name, version)
);
CREATE TABLE IF NOT EXISTS subgraphs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  current_version TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS subgraph_versions (
  subgraph_code TEXT NOT NULL REFERENCES subgraphs(code) ON DELETE CASCADE,
  version TEXT NOT NULL,
  graph JSONB NOT NULL,
  changelog TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (subgraph_code, version)
);
CREATE TABLE IF NOT EXISTS scenarios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  current_version TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS scenario_versions (
  scenario_code TEXT NOT NULL REFERENCES scenarios(code) ON DELETE CASCADE,
  version TEXT NOT NULL,
  graph JSONB NOT NULL,
  enable_saga BOOLEAN NOT NULL DEFAULT TRUE,
  changelog TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (scenario_code, version)
);
CREATE TABLE IF NOT EXISTS deployments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_kind TEXT NOT NULL,
  asset_code TEXT NOT NULL,
  version TEXT NOT NULL,
  env TEXT NOT NULL,
  config_hash TEXT NOT NULL DEFAULT '',
  deployed_by TEXT NOT NULL DEFAULT '',
  deployed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (asset_kind, asset_code, version, env)
);
CREATE TABLE IF NOT EXISTS tests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_kind TEXT NOT NULL,
  subject_code TEXT NOT NULL,
  version TEXT NOT NULL,
  env TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  inputs JSONB,
  output JSONB,
  error TEXT NOT NULL DEFAULT '',
  ran_by TEXT NOT NULL DEFAULT '',
  ran_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS debug_io (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_code TEXT NOT NULL,
  version TEXT NOT NULL,
  env TEXT NOT NULL,
  node_id TEXT NOT NULL,
  inputs JSONB,
  outputs JSONB,
  status TEXT NOT NULL DEFAULT '',
  duration_ms REAL NOT NULL DEFAULT 0,
  reported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debug_io_scenario_idx ON debug_io (scenario_code, version, env, reported_at);
CREATE TABLE IF NOT EXISTS env_containers (
  env TEXT PRIMARY KEY,
  base_url TEXT NOT NULL,
  token TEXT NOT NULL DEFAULT '',
  added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_kind TEXT NOT NULL,
  asset_code TEXT NOT NULL,
  version TEXT NOT NULL,
  env TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  note TEXT NOT NULL DEFAULT '',
  requested_by TEXT NOT NULL DEFAULT '',
  approver TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS approvals_status_idx ON approvals (status, created_at);
CREATE TABLE IF NOT EXISTS locks (
  asset_kind TEXT NOT NULL,
  asset_code TEXT NOT NULL,
  holder TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (asset_kind, asset_code)
);
CREATE TABLE IF NOT EXISTS env_current (
  asset_kind TEXT NOT NULL,
  asset_code TEXT NOT NULL,
  env TEXT NOT NULL,
  version TEXT NOT NULL,
  config_hash TEXT NOT NULL DEFAULT '',
  flow_digest TEXT NOT NULL DEFAULT '',
  deployed_by TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_kind, asset_code, env)
);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS flow_digest TEXT NOT NULL DEFAULT '';
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS flow_definition JSONB;
CREATE TABLE IF NOT EXISTS experiments (
  key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'DRAFT',
  traffic_percent INTEGER NOT NULL DEFAULT 0,
  variants JSONB NOT NULL DEFAULT '[]'::jsonb,
  env_key TEXT NOT NULL DEFAULT 'dev',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS experiment_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_key TEXT NOT NULL REFERENCES experiments(key) ON DELETE CASCADE,
  uid TEXT NOT NULL,
  variant TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (experiment_key, uid)
);
CREATE TABLE IF NOT EXISTS config_namespaces (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS config_items (
  namespace_code TEXT NOT NULL REFERENCES config_namespaces(code) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value_type TEXT NOT NULL DEFAULT 'json',
  description TEXT NOT NULL DEFAULT '',
  gray JSONB NOT NULL DEFAULT '{}'::jsonb,
  current_version TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace_code, key)
);
CREATE TABLE IF NOT EXISTS config_versions (
  namespace_code TEXT NOT NULL,
  key TEXT NOT NULL,
  version TEXT NOT NULL,
  value JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  note TEXT NOT NULL DEFAULT '',
  published_by TEXT NOT NULL DEFAULT '',
  published_at TIMESTAMPTZ,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace_code, key, version),
  FOREIGN KEY (namespace_code, key) REFERENCES config_items(namespace_code, key) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS alert_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '*',
  threshold REAL NOT NULL DEFAULT 3,
  window_minutes INTEGER NOT NULL DEFAULT 60,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  webhook_url TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
  scope_key TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'warning',
  status TEXT NOT NULL DEFAULT 'OPEN',
  occurrences INTEGER NOT NULL DEFAULT 1,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  acked_by TEXT NOT NULL DEFAULT '',
  acked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS alert_events_status_idx ON alert_events (status, last_seen_at);
CREATE INDEX IF NOT EXISTS deployments_asset_idx ON deployments (asset_kind, asset_code, env);
CREATE INDEX IF NOT EXISTS sessions_expires_idx ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS debug_io_reported_idx ON debug_io (reported_at);
"""

SERVICE_TOKEN = os.getenv("ORCH_SERVICE_TOKEN", "orch-service-secret")
BUILTIN_ENVS = [
    ("dev", "http://127.0.0.1:8000"),
    ("test", "http://127.0.0.1:8100"),
    ("staging", "http://127.0.0.1:8101"),
    ("online", "http://127.0.0.1:8102"),
]
ENV_ORDER = {env: i for i, (env, _) in enumerate(BUILTIN_ENVS)}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8,
                                     command_timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None and not _pool._closed:
        await _pool.close()
    _pool = None


async def init_schema() -> dict:
    """建表 + 内置环境 + 首个管理员引导（随机/环境变量密码，一次性打印）。"""
    pool_ = await pool()
    async with pool_.acquire() as conn:
        await conn.execute(SCHEMA)
        for env, base_url in BUILTIN_ENVS:
            await conn.execute(
                "INSERT INTO env_containers (env, base_url, token) VALUES ($1, $2, $3) "
                "ON CONFLICT (env) DO UPDATE SET base_url = $2, token = $3",
                env, base_url, SERVICE_TOKEN,
            )
        admin_password = ""
        row = await conn.fetchrow("SELECT 1 FROM users LIMIT 1")
        if row is None:
            email = os.getenv("ORCH_ADMIN_EMAIL", "admin@orch.local")
            password = os.getenv("ORCH_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
            await conn.execute(
                "INSERT INTO users (email, nickname, password_hash, role) VALUES ($1, $2, $3, 'admin')",
                email, "平台管理员", hash_password(password),
            )
            admin_password = password
    if admin_password:
        return {"bootstrap_admin_email": os.getenv("ORCH_ADMIN_EMAIL", "admin@orch.local"),
                "bootstrap_admin_password": admin_password}
    return {}


# 数据保留期（天）：会话 7 / debug 上报 14 / 已确认告警 30。代码/配置/数据三
# 分离纪律的运营面——无限增长是可靠性的慢性病，清理必须幂等且可重复执行。
RETENTION_DAYS = {"sessions": 7, "debug_io": 14, "alert_events_acked": 30}


async def cleanup_retention(conn=None) -> dict:
    """按保留期清理运行时数据；返回各表删除行数（如实上报，不静默）。

    conn 可注入独立连接（测试/无 pool 环境）；缺省走全局连接池。
    """
    if conn is None:
        pool_ = await pool()
        async with pool_.acquire() as acquired:
            return await cleanup_retention(acquired)
    out = {}
    out["sessions"] = await conn.execute(
        "DELETE FROM sessions WHERE expires_at < now()")
    out["debug_io"] = await conn.execute(
        "DELETE FROM debug_io WHERE reported_at < now() - interval "
        f"'{RETENTION_DAYS['debug_io']} days'")
    out["alert_events_acked"] = await conn.execute(
        "DELETE FROM alert_events WHERE status = 'ACKED' AND acked_at < now() - interval "
        f"'{RETENTION_DAYS['alert_events_acked']} days'")
    return {k: int(v.split()[-1]) for k, v in out.items()}


_retention_task: "asyncio.Task | None" = None


def start_retention_loop() -> None:
    """启动保留期周期清理（幂等：已在跑则不重复）。"""
    global _retention_task
    if _retention_task is None or _retention_task.done():
        _retention_task = asyncio.create_task(_retention_loop())


async def _retention_loop() -> None:
    """每小时执行一次保留期清理；单次失败记录后继续（清理永不中断服务）。"""
    while True:
        await asyncio.sleep(3600)
        try:
            removed = await cleanup_retention()
            if any(removed.values()):
                print(f"[retention] 清理完成：{removed}")
        except Exception as exc:  # noqa: BLE001 - 清理失败不中断循环
            print(f"[retention] 清理失败（下轮重试）：{type(exc).__name__}: {exc}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


async def main_ready() -> bool:
    """确认 asyncpg 就绪（连接探测）。"""
    try:
        pool_ = await pool()
        async with pool_.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1
    except Exception:
        return False
