"""场景注册表：HOST_CONTRACT.md 场景清单的权限点映射与处理器装配。

权限点目录（契约原文）：platform:tenant_manage/user_manage/role_manage/audit_read、
tenant:member_manage/project_create/role_manage、project:manage/member_manage、
orchestration:read/write、experiment:manage/read、configcenter:read/write、
page:ops_console/page:bizops_console。scope 语义：PLATFORM 全局 / TENANT 租户内 /
PROJECT 项目内；本参考实现按"角色权限列表 + 用户-角色绑定"判定。
"""
# 权限点目录（单一来源；scaffold 与 RBAC 校验共用）。
PERMISSION_CATALOG: tuple[dict[str, str], ...] = (
    {"permission": "platform:tenant_manage", "scope": "PLATFORM"},
    {"permission": "platform:user_manage", "scope": "PLATFORM"},
    {"permission": "platform:role_manage", "scope": "PLATFORM"},
    {"permission": "platform:audit_read", "scope": "PLATFORM"},
    {"permission": "tenant:member_manage", "scope": "TENANT"},
    {"permission": "tenant:project_create", "scope": "TENANT"},
    {"permission": "tenant:role_manage", "scope": "TENANT"},
    {"permission": "project:manage", "scope": "PROJECT"},
    {"permission": "project:member_manage", "scope": "PROJECT"},
    {"permission": "orchestration:read", "scope": "PROJECT"},
    {"permission": "orchestration:write", "scope": "PROJECT"},
    {"permission": "experiment:manage", "scope": "PROJECT"},
    {"permission": "experiment:read", "scope": "PROJECT"},
    {"permission": "configcenter:read", "scope": "PROJECT"},
    {"permission": "configcenter:write", "scope": "PROJECT"},
    {"permission": "page:ops_console", "scope": "PLATFORM"},
    {"permission": "page:bizops_console", "scope": "PLATFORM"},
)

# 场景 → 权限点（None = 匿名可达：auth.* 与 scope.my 以会话身份为准）。
SCENARIO_PERMISSIONS: dict[str, str | None] = {
    "auth.login": None,
    "auth.session": None,
    "platform.scope.my": None,
    "platform.tenants.list": "platform:tenant_manage",
    "platform.tenants.create": "platform:tenant_manage",
    "platform.projects.list": "tenant:member_manage",
    "platform.projects.create": "tenant:project_create",
    "platform.projects.update": "project:manage",
    "platform.users.list": "platform:user_manage",
    "platform.users.create": "platform:user_manage",
    "platform.roles.list": "platform:role_manage",
    "platform.roles.create": "platform:role_manage",
    "platform.permissions.list": None,
    "platform.envs.list": "project:manage",
    "platform.envs.create": "project:manage",
    "platform.audit.list": "platform:audit_read",
    "ops.runs.list": "page:ops_console",
    "ops.runs.detail": "page:ops_console",
    "ops.metrics": "page:ops_console",
    "bizops.overview": "page:bizops_console",
    "bizops.trend": "page:bizops_console",
    "bizops.funnel": "page:bizops_console",
    "bizops.retention": "page:bizops_console",
}

# 参考实现刻意不实现编排/实验/配置中心场景：它们由编排控制面（:8200）承载，
# 宿主按契约只做代理接线（边界如实声明，不做占位实现）。
DELEGATED_SCENARIOS_PREFIXES = ("orchestration.", "experiment.", "configcenter.")
