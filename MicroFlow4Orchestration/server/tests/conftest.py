"""Server tests: sys.path setup + shared markers.

纯逻辑测试无需数据库；集成测试需要 PostgreSQL（ORCH_TEST_DATABASE_URL），
缺失时显式跳过并如实报告——不伪造通过。
"""
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import pytest  # noqa: E402

# 集成测试标记：ORCH_TEST_DATABASE_URL 存在时才运行（无 PG 的环境如实跳过）。
requires_pg = pytest.mark.skipif(
    not os.getenv("ORCH_TEST_DATABASE_URL"),
    reason="需要 PostgreSQL：设置 ORCH_TEST_DATABASE_URL 后运行集成测试")
