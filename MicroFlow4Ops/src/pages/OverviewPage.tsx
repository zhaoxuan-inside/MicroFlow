import { useQuery } from "@tanstack/react-query";
import { dispatch } from "@microflow4kit/api";
import { Badge, Card, CardContent, CardHeader, CardTitle, PageHeader, PermissionGate, Spinner, useScope } from "@microflow4kit/ui";

interface MyScopeResp {
  is_platform_super: boolean;
  tenants: unknown[];
  projects: unknown[];
}

interface AuditRow {
  id?: string;
  action: string;
  actor_id?: string;
  result?: string;
  created_at: string;
}

export function OverviewPage() {
  const { hasPermission } = useScope();
  const scope = useQuery({
    queryKey: ["platform", "my-scope"],
    queryFn: () => dispatch<MyScopeResp>("platform.scope.my", {}),
  });
  const canAudit = hasPermission("platform:audit_read") || hasPermission("page:ops_console");
  const audit = useQuery({
    queryKey: ["platform", "audit-count"],
    queryFn: () => dispatch<{ logs: unknown[]; total: number }>("platform.audit.list", { limit: 1 }),
    enabled: canAudit,
  });
  const recent = useQuery({
    queryKey: ["platform", "audit-recent"],
    queryFn: () => dispatch<{ logs: AuditRow[] }>("platform.audit.list", { limit: 6 }),
    enabled: canAudit,
  });

  return (
    <div>
      <PageHeader title="总览" description="运维平台：治理范围与平台事件一览" />
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground">我的租户</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight tabular-nums">
              {scope.isPending ? <Spinner /> : (scope.data?.tenants?.length ?? 0)}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">在册的组织实体</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground">我的项目</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight tabular-nums">
              {scope.isPending ? <Spinner /> : (scope.data?.projects?.length ?? 0)}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">可操作的项目范围</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-muted-foreground">平台管理员</CardTitle>
          </CardHeader>
          <CardContent>
            {scope.isPending ? (
              <Spinner />
            ) : scope.data?.is_platform_super ? (
              <Badge tone="primary">平台超级管理员</Badge>
            ) : (
              <Badge>普通账号</Badge>
            )}
            <p className="mt-2 text-xs text-muted-foreground">平台级通配权限</p>
          </CardContent>
        </Card>
        <PermissionGate anyOf={["platform:audit_read", "page:ops_console"]}>
          <Card>
            <CardHeader>
              <CardTitle className="text-muted-foreground">审计事件（近期）</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold tracking-tight tabular-nums">
                {audit.isPending ? <Spinner /> : (audit.data?.total ?? 0)}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">审计与日志页可按条件检索</p>
            </CardContent>
          </Card>
        </PermissionGate>
      </div>

      <PermissionGate anyOf={["platform:audit_read", "page:ops_console"]}>
        <Card className="mt-4">
          <CardHeader><CardTitle>最近平台事件</CardTitle></CardHeader>
          <CardContent>
            {recent.isPending ? (
              <div className="flex justify-center py-8"><Spinner /></div>
            ) : !recent.data?.logs?.length ? (
              <p className="py-4 text-center text-xs text-muted-foreground">暂无审计事件；平台操作留痕后此处实时更新。</p>
            ) : (
              <ul className="divide-y divide-border/60 text-xs">
                {recent.data.logs.map((row, idx) => (
                  <li key={row.id || idx} className="flex items-center gap-3 py-2">
                    <span className="shrink-0 tabular-nums font-mono text-muted-foreground">
                      {row.created_at?.slice(0, 19).replace("T", " ")}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium font-mono">{row.action}</span>
                    <span className="shrink-0 truncate font-mono text-muted-foreground">{row.actor_id || "—"}</span>
                    {row.result === "SUCCESS" ? (
                      <Badge tone="success">SUCCESS</Badge>
                    ) : row.result ? (
                      <Badge tone="destructive">{row.result}</Badge>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </PermissionGate>
    </div>
  );
}
