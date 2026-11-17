import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  ConfirmDialog,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  PageHeader,
  Select,
  Spinner,
  cn,
} from "@microflow4kit/ui";
import { diffLines } from "@microflow4kit/ui";
import { PermissionGate } from "../orchAuth";
import { orchDispatch } from "../orchClient";

interface VersionRow {
  version: string;
  changelog?: string;
  created_by?: string;
  created_at?: string;
}
interface ScenarioDetail {
  code: string;
  current_version?: string;
  versions: VersionRow[];
  deployments: Record<string, string[]>;
}
interface CurrentRow {
  env: string;
  version: string;
  config_hash: string;
  flow_digest: string;
  updated_at: string;
}
interface ApprovalRow {
  id: string;
  asset_kind: string;
  asset_code: string;
  version: string;
  env: string;
  status: string;
  note?: string;
  requested_by: string;
  approver?: string;
  created_at?: string;
  decided_at?: string;
}
interface DiffSide {
  version: string;
  graph: unknown;
  config_hash: string;
  flow_digest: string | null;
}

const ENVS = ["dev", "test", "staging", "online"] as const;
const APPROVAL_ENVS = ["staging", "online"] as const;

export function ReleasesPage() {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [rollbackTo, setRollbackTo] = useState("");
  const [rollbackEnv, setRollbackEnv] = useState<(typeof ENVS)[number]>("online");
  const [approvalEnv, setApprovalEnv] = useState<(typeof APPROVAL_ENVS)[number]>("staging");
  const [error, setError] = useState("");

  const scenarios = useQuery({
    queryKey: ["catalog-scenarios"],
    queryFn: () =>
      orchDispatch<{ scenarios: Array<{ code: string; display_name?: string }> }>(
        "GET", `/scenarios?page=1&page_size=200`),
  });

  const detail = useQuery({
    queryKey: ["scenario-detail", code],
    enabled: !!code,
    queryFn: () => orchDispatch<ScenarioDetail>("GET", `/scenarios/${encodeURIComponent(code)}`),
  });

  const deployments = useQuery({
    queryKey: ["scenario-deployments", code],
    enabled: !!code,
    queryFn: () =>
      orchDispatch<{ deployments: Array<Record<string, unknown>>; current: Record<string, CurrentRow> }>(
        "GET", `/scenarios/${encodeURIComponent(code)}/deployments`),
  });

  const approvals = useQuery({
    queryKey: ["release-approvals"],
    queryFn: () => orchDispatch<{ approvals: ApprovalRow[] }>("GET", "/approvals"),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["scenario-detail", code] });
    qc.invalidateQueries({ queryKey: ["scenario-deployments", code] });
    qc.invalidateQueries({ queryKey: ["release-approvals"] });
  };

  const run = useMutation({
    mutationFn: async ({ method, path, payload }: { method: "POST"; path: string; payload?: Record<string, unknown> }) => {
      const result = await orchDispatch<Record<string, unknown>>(method, path, payload);
      invalidate();
      return result;
    },
    onError: (e) => setError((e as Error).message),
    onSuccess: () => setError(""),
  });

  const versions = detail.data?.versions || [];
  const current = deployments.data?.current || {};
  const currentEnvsOf = (version: string) =>
    ENVS.filter((env) => current[env]?.version === version);
  const deployedEnvsOf = (version: string) => detail.data?.deployments?.[version] || [];
  const diffable = useMemo(
    () => Array.from(new Set([...(detail.data?.deployments ? Object.keys(detail.data.deployments) : [])])),
    [detail.data],
  );

  const diff = useQuery({
    queryKey: ["scenario-diff", code, left, right],
    enabled: !!code && !!left && !!right,
    queryFn: () =>
      orchDispatch<{ left: DiffSide; right: DiffSide }>(
        "GET",
        `/scenarios/${encodeURIComponent(code)}/version-diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
      ),
  });

  const diffRows = useMemo(() => {
    if (!diff.data?.left?.graph || !diff.data?.right?.graph) return null;
    return diffLines(
      JSON.stringify(diff.data.left.graph, null, 2),
      JSON.stringify(diff.data.right.graph, null, 2),
    );
  }, [diff.data]);

  return (
    <div>
      <PageHeader
        title="版本与发布"
        description="场景版本历史 / 部署 diff / 回滚（每环境生效指针）/ 第二人发布审批"
      />

      <div className="mb-4 flex items-center gap-2">
        <Input
          list="scenario-codes"
          placeholder="选择或输入场景编码…"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="max-w-xs"
        />
        <datalist id="scenario-codes">
          {(scenarios.data?.scenarios || []).map((s) => (
            <option key={s.code} value={s.code}>
              {s.display_name || s.code}
            </option>
          ))}
        </datalist>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {code && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>版本历史 {detail.isPending && <Spinner className="ml-2" />}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {versions.map((v) => {
                const envs = deployedEnvsOf(v.version);
                const active = currentEnvsOf(v.version);
                return (
                  <div
                    key={v.version}
                    className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium font-mono">{v.version}</span>
                        {envs.length > 0 && <Badge tone="success">已部署 {envs.join("/")}</Badge>}
                        {active.map((env) => (
                          <Badge key={env} tone="primary">{env} 生效中</Badge>
                        ))}
                        {detail.data?.current_version === v.version && (
                          <Badge tone="neutral">最新草稿</Badge>
                        )}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {v.changelog || "—"} {v.created_by ? `· ${v.created_by}` : ""}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <PermissionGate permission="orchestration:write">
                        <Select
                          className="h-8 w-28 text-xs"
                          value={rollbackEnv}
                          onChange={(e) => setRollbackEnv(e.target.value as (typeof ENVS)[number])}
                          aria-label="回滚目标环境"
                        >
                          {ENVS.map((env) => <option key={env} value={env}>{env}</option>)}
                        </Select>
                        <Button
                          variant="secondary"
                          onClick={() => setRollbackTo(v.version)}
                          disabled={run.isPending}
                        >
                          回滚到此版本
                        </Button>
                        <Select
                          className="h-8 w-24 text-xs"
                          value={approvalEnv}
                          onChange={(e) => setApprovalEnv(e.target.value as (typeof APPROVAL_ENVS)[number])}
                          aria-label="审批目标环境"
                        >
                          {APPROVAL_ENVS.map((env) => <option key={env} value={env}>{env}</option>)}
                        </Select>
                        <Button
                          variant="secondary"
                          onClick={() =>
                            run.mutate({
                              method: "POST",
                              path: "/approvals/request",
                              payload: { asset_kind: "scenario", asset_code: code,
                                         version: v.version, env: approvalEnv },
                            })
                          }
                          disabled={run.isPending}
                        >
                          提交发布审批
                        </Button>
                      </PermissionGate>
                    </div>
                  </div>
                );
              })}
              {!detail.isPending && !versions.length && (
                <EmptyState title="该场景没有版本记录" />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>部署 diff（选择两个已部署版本）</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-3 flex items-center gap-2">
                <Select
                  className="h-9 w-44 text-sm"
                  value={left}
                  onChange={(e) => setLeft(e.target.value)}
                  aria-label="选择 diff 左侧版本"
                >
                  <option value="">左…</option>
                  {diffable.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </Select>
                <span className="text-muted-foreground">→</span>
                <Select
                  className="h-9 w-44 text-sm"
                  value={right}
                  onChange={(e) => setRight(e.target.value)}
                  aria-label="选择 diff 右侧版本"
                >
                  <option value="">右…</option>
                  {diffable.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </Select>
              </div>
              {diff.isPending && (left && right) ? (
                <Spinner />
              ) : diffRows ? (
                <div>
                  <div className="mb-2 text-xs text-muted-foreground">
                    左 config_hash <code className="font-mono">{diff.data?.left.config_hash.slice(0, 12)}…</code>
                    · 右 <code className="font-mono">{diff.data?.right.config_hash.slice(0, 12)}…</code>
                    {diff.data?.right.flow_digest ? (
                      <> · flow_digest <code className="font-mono">{diff.data.right.flow_digest.slice(0, 12)}…</code></>
                    ) : null}
                  </div>
                  <div className="max-h-96 overflow-auto rounded-md border border-border font-mono text-xs">
                    {diffRows.map((row, idx) => (
                      <div
                        key={idx}
                        className={cn(
                          "grid grid-cols-2 gap-px",
                          row.kind === "added" && "bg-success/8",
                          row.kind === "removed" && "bg-destructive/8",
                        )}
                      >
                        <pre className={cn("px-2 py-0.5", row.kind === "removed" && "text-destructive")}>
                          {row.left || ""}
                        </pre>
                        <pre className={cn("px-2 py-0.5", row.kind === "added" && "text-success")}>
                          {row.right || ""}
                        </pre>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <EmptyState title="选择左右两个版本查看部署差异" />
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>发布审批（第二人确认制 · staging/online）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {approvals.isPending ? (
            <Spinner />
          ) : !approvals.data?.approvals?.length ? (
            <EmptyState title="暂无审批单" hint="在版本历史里对版本提交发布审批" />
          ) : (
            approvals.data.approvals.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2"
              >
                <div className="min-w-0 text-sm">
                  <span className="font-medium font-mono">
                    {a.asset_kind} {a.asset_code}@{a.version} → {a.env}
                  </span>
                  <span className="ml-2 text-xs tabular-nums text-muted-foreground">
                    发起 {a.requested_by} · {a.created_at?.slice(0, 19).replace("T", " ")}
                  </span>
                  {a.note && <div className="truncate text-xs text-muted-foreground">{a.note}</div>}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge
                    tone={
                      a.status === "APPROVED"
                        ? "success"
                        : a.status === "PENDING"
                          ? "warning"
                          : "destructive"
                    }
                  >
                    {a.status}
                  </Badge>
                  {a.status === "PENDING" && (
                    <PermissionGate permission="orchestration:write">
                      <Button
                        variant="secondary"
                        onClick={() =>
                          run.mutate({ method: "POST", path: "/approvals/decide",
                                       payload: { approval_id: a.id, decision: "reject" } })
                        }
                      >
                        驳回
                      </Button>
                      <Button
                        onClick={() =>
                          run.mutate({ method: "POST", path: "/approvals/decide",
                                       payload: { approval_id: a.id, decision: "approve" } })
                        }
                      >
                        通过并执行
                      </Button>
                    </PermissionGate>
                  )}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={rollbackTo !== ""}
        title="回滚发布版本"
        description={`确认将「${code}」的 ${rollbackEnv} 环境回滚到版本 ${rollbackTo}？该环境生效指针立即切换，新执行按回滚后版本装载（阶段守卫与 E2E 门禁照常生效）。`}
        confirmLabel="确认回滚"
        onConfirm={() => {
          run.mutate({
            method: "POST",
            path: `/scenarios/${encodeURIComponent(code)}/rollback`,
            payload: { version: rollbackTo, env: rollbackEnv },
          });
          setRollbackTo("");
        }}
        onCancel={() => setRollbackTo("")}
      />
    </div>
  );
}
