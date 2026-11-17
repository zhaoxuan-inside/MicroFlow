import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
} from "@microflow4kit/ui";
import { clearOrchToken, getOrchToken, onOrchUnauthorized, orchRest, setOrchToken } from "@microflow4kit/api";

interface AlertEvent {
  id: string;
  rule_name: string;
  rule_kind: string;
  scope_key: string;
  message: string;
  severity: string;
  status: string;
  occurrences: number;
  detail: Record<string, unknown>;
  first_seen_at?: string;
  last_seen_at?: string;
  acked_by?: string;
  acked_at?: string;
}
interface AlertRule {
  id: string;
  name: string;
  kind: string;
  target: string;
  threshold: number;
  window_minutes: number;
  enabled: boolean;
  webhook_url: string;
}

/** 控制面登录面（内联）：告警数据由控制面承载，需要控制面账号会话。 */
function OrchLogin({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const login = useMutation({
    mutationFn: () =>
      orchRest<{ token: string }>("POST", "/auth/login", { email, password }),
    onSuccess: (data) => {
      setOrchToken(data.token);
      onDone();
    },
    onError: (e) => setError((e as Error).message),
  });
  return (
    <Card className="mx-auto mt-10 max-w-sm">
      <CardHeader>
        <CardTitle>登录控制面</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          告警事件由编排控制面承载（独立账号体系），与运维平台的宿主账号相互独立。
        </p>
        <Field label="邮箱">
          <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
        </Field>
        <Field label="密码">
          <Input value={password} onChange={(e) => setPassword(e.target.value)} type="password" />
        </Field>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button className="w-full" onClick={() => login.mutate()} disabled={login.isPending}>
          {login.isPending ? <Spinner /> : "登录"}
        </Button>
      </CardContent>
    </Card>
  );
}

export function AlertsPage() {
  const qc = useQueryClient();
  const [token, setToken] = useState(() => Boolean(getOrchToken()));
  const [statusFilter, setStatusFilter] = useState("OPEN");

  useEffect(() => {
    // 401 统一兜底：清 token 后页面回落到控制面登录面。
    onOrchUnauthorized(() => setToken(false));
    return () => onOrchUnauthorized(null);
  }, []);

  const session = useQuery({
    queryKey: ["orch-session"],
    enabled: token,
    queryFn: () => orchRest<{ role: string; permissions: string[] }>("GET", "/auth/me"),
    retry: false,
  });

  const alerts = useQuery({
    queryKey: ["orch-alerts", statusFilter],
    enabled: token && Boolean(session.data),
    queryFn: () =>
      orchRest<{ alerts: AlertEvent[] }>("GET", `/alerts?status=${encodeURIComponent(statusFilter)}`),
  });

  const rules = useQuery({
    queryKey: ["orch-alert-rules"],
    enabled: token && Boolean(session.data),
    queryFn: () => orchRest<{ rules: AlertRule[] }>("GET", "/alerts/rules"),
  });

  const ack = useMutation({
    mutationFn: (id: string) => orchRest("POST", `/alerts/${id}/ack`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orch-alerts"] }),
  });

  if (!token) {
    return <OrchLogin onDone={() => setToken(true)} />;
  }
  if (session.isPending) {
    return <Spinner className="mx-auto mt-10" />;
  }
  if (session.isError || !session.data?.permissions?.includes("ops:alerts")) {
    return (
      <Card className="mx-auto mt-10 max-w-md">
        <CardContent className="pt-6 text-center text-sm text-muted-foreground">
          当前控制面账号没有 ops:alerts 权限（admin/editor 可用）。
          <Button variant="ghost" className="ml-2 h-8" onClick={() => { clearOrchToken(); setToken(false); qc.clear(); }}>
            切换账号
          </Button>
        </CardContent>
      </Card>
    );
  }

  const severityTone = (value: string) =>
    value === "critical" ? "destructive" : value === "warning" ? "warning" : "neutral";
  const statusTone = (value: string) => (value === "OPEN" ? "destructive" : "success");

  return (
    <div>
      <PageHeader
        title="告警中心"
        description="规则求值（连续失败 / 错误率）· 事件确认（ack）· 规则只读视图（规则管理在控制面）"
      />

      <div className="mb-4 flex items-center gap-2">
        <Select
          className="h-9 w-40 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="告警状态过滤"
        >
          <option value="OPEN">未确认</option>
          <option value="ACKED">已确认</option>
          <option value="">全部</option>
        </Select>
        <span className="text-xs text-muted-foreground">数据源：编排控制面（debug I/O 上报与场景执行结果实时求值）</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>告警事件 {alerts.isPending && <Spinner className="ml-2" />}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {alerts.isError && (
            <p className="text-sm text-destructive">{(alerts.error as Error).message}</p>
          )}
          {!alerts.isPending && !alerts.data?.alerts?.length && (
            <EmptyState title="暂无告警事件" hint="规则命中后自动生成；同规则未确认只累计不重复开" />
          )}
          {alerts.data?.alerts?.map((a) => (
            <div
              key={a.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2"
            >
              <div className="min-w-0 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={severityTone(a.severity)}>{a.severity}</Badge>
                  <Badge tone={statusTone(a.status)}>{a.status}</Badge>
                  <span className="font-medium">{a.rule_name}</span>
                  <code className="font-mono text-xs text-muted-foreground">{a.scope_key}</code>
                  <span className="text-xs tabular-nums text-muted-foreground">×{a.occurrences}</span>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">{a.message}</div>
                <div className="text-xs tabular-nums text-muted-foreground">
                  首次 {a.first_seen_at?.slice(0, 19).replace("T", " ") || "—"} · 最近{" "}
                  {a.last_seen_at?.slice(0, 19).replace("T", " ") || "—"}
                  {a.acked_by ? ` · 确认 ${a.acked_by}` : ""}
                </div>
              </div>
              {a.status === "OPEN" && (
                <Button variant="secondary" onClick={() => ack.mutate(a.id)} disabled={ack.isPending}>
                  确认
                </Button>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>告警规则（只读）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {!rules.isPending && !rules.data?.rules?.length && (
            <EmptyState title="暂无规则" hint="规则管理接口：POST/DELETE /api/alerts/rules（控制面）" />
          )}
          {rules.data?.rules?.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                <span className="font-medium">{r.name}</span>
                <code className="ml-2 font-mono text-xs text-muted-foreground">
                  {r.kind === "consecutive_failures" ? "连续失败" : "错误率"} · 目标 {r.target} · 阈值{" "}
                  {r.threshold}
                  {r.kind === "error_rate" ? "%" : ` 次`}
                  {r.kind === "error_rate" ? ` · 窗口 ${r.window_minutes} 分钟` : ""}
                </code>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {r.webhook_url && <Badge tone="neutral">webhook</Badge>}
                <Badge tone={r.enabled ? "success" : "neutral"}>{r.enabled ? "启用" : "停用"}</Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
