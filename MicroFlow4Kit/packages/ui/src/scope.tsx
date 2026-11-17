/** Scope context: 我的身份、可操作的租户/项目、生效权限（分租户·分权限前端镜像）。
 *
 * 数据源是后端 platform.scope.my；活动选择持久化在 console-api 的 scope 存储，
 * dispatch 自动注入 context。权限判定与后端同构：平台超管通配，PLATFORM ∪
 * 活动租户 ∪ 活动项目 的角色权限并集。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dispatch,
  getScope,
  getToken,
  onScopeChange,
  onSessionChange,
  setScope as persistScope,
  type ConsoleScope,
} from "@microflow4kit/api";
import { Badge, Button, Card, CardContent, cn } from "./primitives";

interface RoleSummary {
  role_id: string;
  name: string;
  code: string;
  permissions: string[];
}

interface MyScope {
  user_id: string;
  is_platform_super: boolean;
  tenants: Array<{
    tenant_id: string;
    code: string;
    name: string;
    status: string;
    role: RoleSummary;
  }>;
  projects: Array<{
    project_id: string;
    tenant_id: string;
    tenant_name: string;
    key: string;
    name: string;
    status: string;
    role: RoleSummary;
    environments?: EnvironmentInfo[];
  }>;
  platform_roles: RoleSummary[];
}

interface EnvironmentInfo {
  env_id: string;
  key: string;
  name: string;
  protected: boolean;
}

interface ScopeContextValue {
  myScope: MyScope | undefined;
  loading: boolean;
  scope: ConsoleScope;
  activeTenant: MyScope["tenants"][number] | undefined;
  activeProject: MyScope["projects"][number] | undefined;
  activeEnvironments: EnvironmentInfo[];
  selectTenant: (tenantId: string) => void;
  selectProject: (projectId: string) => void;
  selectEnvironment: (envKey: string) => void;
  hasPermission: (permission: string) => boolean;
  refresh: () => void;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setLocalScope] = useState<ConsoleScope>(() => getScope());
  const [sessionGeneration, setSessionGeneration] = useState(0);
  const parentClient = useQueryClient();
  // Cache and page-local state belong to one tenant/project/environment only.
  const scopeKey = JSON.stringify([sessionGeneration, scope.tenantId, scope.projectId, scope.envKey]);
  const scopedClient = useMemo(() => new QueryClient({
    defaultOptions: parentClient.getDefaultOptions(),
  }), [parentClient, scopeKey]);

  useEffect(() => () => {
    void scopedClient.cancelQueries();
    scopedClient.clear();
  }, [scopedClient]);

  useEffect(() => {
    return onScopeChange((next) => setLocalScope(next));
  }, []);

  useEffect(() => onSessionChange(() => setSessionGeneration((value) => value + 1)), []);

  const q = useQuery({
    queryKey: ["platform", "my-scope", sessionGeneration],
    queryFn: () => dispatch<MyScope>("platform.scope.my", {}),
    enabled: Boolean(getToken()),
    retry: false,
  });

  const myScope = q.data;

  // 活动项目决定活动租户（项目挂在租户下）；悬空选择自动回落
  const activeProject = useMemo(
    () => myScope?.projects.find((p) => p.project_id === scope.projectId),
    [myScope, scope.projectId],
  );
  const effectiveTenantId = activeProject?.tenant_id || scope.tenantId;
  const activeTenant = useMemo(
    () => myScope?.tenants.find((t) => t.tenant_id === effectiveTenantId),
    [myScope, effectiveTenantId],
  );

  const selectTenant = useCallback(
    (tenantId: string) => {
      const next = { tenantId, projectId: "", envKey: "" };
      persistScope(next);
      setLocalScope(next);
    },
    [],
  );

  const selectProject = useCallback(
    (projectId: string) => {
      const project = myScope?.projects.find((p) => p.project_id === projectId);
      const next = { tenantId: project?.tenant_id || "", projectId, envKey: "" };
      persistScope(next);
      setLocalScope(next);
    },
    [myScope],
  );

  const selectEnvironment = useCallback(
    (envKey: string) => {
      const next = { ...getScope(), envKey };
      persistScope(next);
      setLocalScope(next);
    },
    [],
  );

  const hasPermission = useCallback(
    (permission: string) => {
      if (!myScope) return false;
      if (myScope.is_platform_super) return true;
      const granted = new Set<string>();
      for (const role of myScope.platform_roles || []) {
        for (const p of role.permissions || []) granted.add(p);
      }
      if (activeTenant?.role) {
        for (const p of activeTenant.role.permissions || []) granted.add(p);
      }
      if (activeProject?.role) {
        for (const p of activeProject.role.permissions || []) granted.add(p);
      }
      return granted.has(permission) || granted.has("*");
    },
    [myScope, activeTenant, activeProject],
  );

  const refresh = useCallback(() => {
    q.refetch();
  }, [q]);

  const activeEnvironments: EnvironmentInfo[] = activeProject?.environments || [];
  const value: ScopeContextValue = {
    myScope,
    loading: q.isPending,
    scope: { tenantId: effectiveTenantId || "", projectId: activeProject?.project_id || "", envKey: scope.envKey },
    activeTenant,
    activeProject,
    activeEnvironments,
    selectTenant,
    selectProject,
    selectEnvironment,
    hasPermission,
    refresh,
  };

  return <ScopeContext.Provider value={value}>
    <QueryClientProvider key={scopeKey} client={scopedClient}>{children}</QueryClientProvider>
  </ScopeContext.Provider>;
}

export function useScope(): ScopeContextValue {
  const ctx = useContext(ScopeContext);
  if (!ctx) throw new Error("useScope 必须在 ScopeProvider 内使用");
  return ctx;
}

/** 条件渲染：仅在持有指定权限点（或任一权限点）时渲染 children。 */
export function PermissionGate({
  permission,
  anyOf,
  children,
  fallback = null,
}: {
  permission?: string;
  anyOf?: string[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { hasPermission, loading } = useScope();
  if (loading) return null;
  const granted = permission ? hasPermission(permission) : false;
  const grantedAny = (anyOf || []).some((p) => hasPermission(p));
  return <>{granted || grantedAny ? children : fallback}</>;
}

/** 租户 → 项目级联切换器（支撑平台头部）。 */
export function ScopeSwitcher({ className }: { className?: string }) {
  const { t } = useTranslation("ui");
  const { myScope, activeTenant, activeProject, activeEnvironments, scope, selectTenant, selectProject, selectEnvironment } = useScope();

  if (!myScope) return null;
  const projects = myScope.projects.filter(
    (p) => !activeTenant || p.tenant_id === activeTenant.tenant_id,
  );

  return (
    <Card className={cn("border-border/60", className)}>
      <CardContent className="flex flex-wrap items-center gap-2 px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">{t("scope.label")}</span>
        <select
          aria-label={t("scope.selectTenant")}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs"
          value={activeTenant?.tenant_id || ""}
          onChange={(e) => selectTenant(e.target.value)}
        >
          <option value="">{t("scope.noTenant")}</option>
          {myScope.tenants.map((tenant) => (
            <option key={tenant.tenant_id} value={tenant.tenant_id}>
              {tenant.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t("scope.selectProject")}
          className="h-8 rounded-md border border-border bg-background px-2 text-xs"
          value={activeProject?.project_id || ""}
          onChange={(e) => selectProject(e.target.value)}
        >
          <option value="">{t("scope.noProject")}</option>
          {projects.map((project) => (
            <option key={project.project_id} value={project.project_id}>
              {project.name}
            </option>
          ))}
        </select>
        {activeProject && (
          <select
            aria-label={t("scope.selectEnv")}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs"
            value={scope.envKey}
            onChange={(e) => selectEnvironment(e.target.value)}
          >
            <option value="">{t("scope.defaultEnv")}</option>
            {activeEnvironments.map((env) => (
              <option key={env.key} value={env.key}>
                {env.name}{env.protected ? " 🔒" : ""}
              </option>
            ))}
          </select>
        )}
        {activeProject?.role?.name ? (
          <Badge tone="primary">{activeProject.role.name}</Badge>
        ) : activeTenant?.role?.name ? (
          <Badge>{activeTenant.role.name}</Badge>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** 无任何租户/项目授权时的空态引导。 */
export function ScopeEmptyHint({ hint }: { hint?: string }) {
  const { t } = useTranslation("ui");
  const { myScope, loading } = useScope();
  if (loading || !myScope) return null;
  if (myScope.is_platform_super || myScope.tenants.length > 0) return null;
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-start gap-2 px-5 py-4">
        <div className="text-sm font-medium">{t("scope.emptyTitle")}</div>
        <div className="text-xs text-muted-foreground">
          {hint || t("scope.emptyHint")}
        </div>
        <Button variant="secondary" className="h-7 text-xs" onClick={() => window.location.reload()}>
          {t("common.refreshAuth")}
        </Button>
      </CardContent>
    </Card>
  );
}
