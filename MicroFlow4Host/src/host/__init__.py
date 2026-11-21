"""MicroFlow4Host：宿主参考实现（dispatch 网关 + 治理 + 遥测 + 聚合 + 托管 + scaffold）。"""
from .app import create_app
from .database import HostDatabase
from .scenarios import PERMISSION_CATALOG, SCENARIO_PERMISSIONS

__all__ = ["create_app", "HostDatabase", "PERMISSION_CATALOG", "SCENARIO_PERMISSIONS"]
