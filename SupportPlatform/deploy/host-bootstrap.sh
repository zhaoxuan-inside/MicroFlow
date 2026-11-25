#!/bin/sh
# 宿主管理员引导（可重入）：已存在则跳过，首跑用显式口令建立管理员。
# bootstrap CLI 本身幂等拒绝重建（口令只打印一次纪律）；本包装层把
# "已存在"从失败转成跳过，供 compose 的 service_completed_successfully 复用。
set -eu

STORE="${MF_HOST_STORE:-/data/host.sqlite3}"
ADMIN="${MF_DEV_ADMIN:-dev-admin}"
PASSWORD="${MF_DEV_PASSWORD:-dev-password}"

if python - "$STORE" "$ADMIN" 2>/dev/null <<'PY'
import sqlite3, sys
store, admin = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
row = conn.execute("SELECT 1 FROM users WHERE name = ?", (admin,)).fetchone()
sys.exit(0 if row else 1)
PY
then
  echo "[bootstrap] admin ${ADMIN} already exists (skip)"
else
  microflow-host bootstrap --store "$STORE" --admin "$ADMIN" --password "$PASSWORD"
fi
