/** 运行记录 = dispatch 调用记录（真源：宿主 runs 表）；事件瀑布 = registry 事件流
 * （ops.events.list，按聚合键分组）。字段与宿主契约（host-contract.fields.json v1）
 * 逐字对齐：不再读取宿主不存在的 node_traces / trace_id，节点级事实走事件流。 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dispatch } from "@microflow4kit/api";
import {
  frameToTrace,
  groupFramesByAggregate,
  maxDurationOf,
  waterfallPct,
  type EventFrameLike,
} from "../lib/waterfall";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  cn,
  EmptyState,
  Field,
  Input,
  PageHeader,
  PermissionGate,
  Select,
  Spinner,
} from "@microflow4kit/ui";

interface RunRow {
  seq: number;
  at: string;
  scenario: string;
  status: string;
  duration_ms: number;
  actor: string | null;
  tenant_id: number | null;
  project_id: number | null;
  env_key: string | null;
}

type EventRow = EventFrameLike & { received_at: string };

const statusTone: Record<string, "success" | "destructive" | "neutral"> = {
  SUCCEEDED: "success",
  FAILED: "destructive",
};

export function RunsPage() {
  const [scenario, setScenario] = useState("");
  const [status, setStatus] = useState("");
  const [envKey, setEnvKey] = useState("");
  const [aggregate, setAggregate] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["ops", "runs", scenario, status, envKey],
    queryFn: () => dispatch<{ runs: RunRow[]; total: number }>("ops.runs.list", {
      scenario: scenario || undefined,
      status: status || undefined,
      env_key: envKey || undefined,
      limit: 200,
    }),
  });
  const detail = useQuery({
    queryKey: ["ops", "run-detail", selected],
    queryFn: () => dispatch<{ run: RunRow }>("ops.runs.detail", { seq: selected as number }),
    enabled: selected !== null,
  });
  const events = useQuery({
    queryKey: ["ops", "events", aggregate],
    queryFn: () => dispatch<{ events: EventRow[]; total: number }>("ops.events.list", {
      aggregate_key: aggregate || undefined,
      limit: 100,
    }),
  });

  const rows = list.data?.runs || [];
  const groups = groupFramesByAggregate(events.data?.events || []);

  return (
    <div>
      <PageHeader
        title="运行记录"
        description="dispatch 调用记录 + registry 事件瀑布——节点级时长来自业务容器上报的真实帧"
      />
      <PermissionGate
        permission="platform:audit_read"
        fallback={<Card className="p-6 text-sm text-muted-foreground">需要运维可观测读权限（platform:audit_read）。</Card>}
      >
        <Card className="mb-4">
          <CardContent className="flex flex-wrap items-end gap-3 px-4 py-3">
            <Field label="场景">
              <Input className="h-8 w-64 text-xs" value={scenario} onChange={(e) => setScenario(e.target.value)}
                placeholder="如 registry.stream" />
            </Field>
            <Field label="状态">
              <Select className="h-8 w-32 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">全部</option>
                <option value="SUCCEEDED">SUCCEEDED</option>
                <option value="FAILED">FAILED</option>
              </Select>
            </Field>
            <Field label="环境">
              <Select className="h-8 w-32 text-xs" value={envKey} onChange={(e) => setEnvKey(e.target.value)}>
                <option value="">全部</option>
                <option value="dev">开发</option>
                <option value="test">测试</option>
                <option value="staging">预上线</option>
                <option value="online">线上</option>
              </Select>
            </Field>
          </CardContent>
        </Card>

        <Card className="mb-4">
          {list.isPending ? (
            <div className="flex justify-center py-16"><Spinner /></div>
          ) : !rows.length ? (
            <div className="p-5"><EmptyState title="没有匹配的运行记录" hint="记录随 dispatch 调用实时产生；过滤条件对齐宿主契约（scenario/status/env_key）。" /></div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium font-mono uppercase">时间</th>
                  <th className="px-4 py-2.5 font-medium font-mono uppercase">场景</th>
                  <th className="px-4 py-2.5 font-medium font-mono uppercase">状态</th>
                  <th className="px-4 py-2.5 font-medium font-mono uppercase">耗时</th>
                  <th className="px-4 py-2.5 font-medium font-mono uppercase">操作者</th>
                  <th className="px-4 py-2.5 font-medium font-mono uppercase"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.seq} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                    <td className="px-4 py-2.5 text-xs tabular-nums text-muted-foreground">{r.at?.slice(11, 19)}</td>
                    <td className="px-4 py-2.5 text-xs font-medium font-mono">
                      {r.scenario}
                      {r.env_key ? <Badge className="ml-1">{r.env_key}</Badge> : null}
                    </td>
                    <td className="px-4 py-2.5"><Badge tone={statusTone[r.status] || "neutral"}>{r.status}</Badge></td>
                    <td className="px-4 py-2.5 text-xs tabular-nums">{r.duration_ms}ms</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{r.actor || "—"}</td>
                    <td className="px-4 py-2.5">
                      <Button variant="secondary" className="h-7 text-xs" onClick={() => setSelected(r.seq)}>
                        详情
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        {selected !== null && detail.data && (
          <Card className="mb-4">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  调用记录 · #{detail.data.run.seq} {detail.data.run.scenario}
                  <Badge tone={statusTone[detail.data.run.status] || "neutral"} className="ml-2">
                    {detail.data.run.status}
                  </Badge>
                </CardTitle>
                <Button variant="secondary" className="h-7 text-xs" onClick={() => setSelected(null)}>收起</Button>
              </div>
              <p className="font-mono text-xs text-muted-foreground">
                调用级记录（runs 表真实字段）；节点级瀑布见下方事件流
              </p>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-xs md:grid-cols-4">
                {([
                  ["时间", detail.data.run.at],
                  ["耗时", `${detail.data.run.duration_ms}ms`],
                  ["操作者", detail.data.run.actor || "—"],
                  ["租户", detail.data.run.tenant_id ?? "—"],
                  ["项目", detail.data.run.project_id ?? "—"],
                  ["环境", detail.data.run.env_key || "—"],
                ] as const).map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="font-mono tabular-nums">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-base">事件瀑布</CardTitle>
              <Field label="聚合键">
                <Input className="h-8 w-56 text-xs" value={aggregate} onChange={(e) => setAggregate(e.target.value)}
                  placeholder="如 exec-6f1c；留空看最新" />
              </Field>
            </div>
            <p className="text-xs text-muted-foreground">
              microflow-registry stream 上报的真实帧（at-least-once，按 event_id 去重后）；条宽 = 帧内 duration_ms
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {events.isPending ? (
              <div className="flex justify-center py-10"><Spinner /></div>
            ) : !groups.length ? (
              <EmptyState title="没有事件帧" hint="业务容器经 microflow-registry stream 上报后出现在这里（registry.stream 场景）。" />
            ) : (
              groups.map(({ aggregateKey, frames }) => {
                const traces = frames.map(frameToTrace);
                const max = maxDurationOf(traces);
                const failed = traces.filter((t) => t.status !== "SUCCEEDED" && t.status !== "UNKNOWN").length;
                return (
                  <div key={aggregateKey} className="rounded-md border border-border/60 p-3">
                    <div className="mb-2 flex items-center gap-2 text-xs">
                      <span className="font-mono font-medium">{aggregateKey}</span>
                      <Badge>{frames.length} 帧</Badge>
                      {failed ? <Badge tone="destructive">异常 {failed}</Badge> : null}
                      <span className="ml-auto text-muted-foreground">max {max}ms</span>
                    </div>
                    <div className="space-y-1.5">
                      {frames.map((frame, index) => {
                        const trace = traces[index];
                        return (
                          <details key={frame.event_id} className="group">
                            <summary className="flex cursor-pointer list-none items-center gap-2 text-xs">
                              <span className="w-40 shrink-0 truncate font-medium">{trace.node_id}</span>
                              <div className="h-4 min-w-0 flex-1 rounded-sm bg-muted/60">
                                <div
                                  className={cn(
                                    "h-4 rounded-sm",
                                    trace.status === "SUCCEEDED" ? "bg-primary/60"
                                      : trace.status === "UNKNOWN" ? "bg-muted-foreground/40" : "bg-destructive/70",
                                  )}
                                  style={{ width: `${waterfallPct(trace.duration_ms, max)}%` }}
                                  title={`${trace.duration_ms}ms`}
                                />
                              </div>
                              <span className="w-20 shrink-0 text-right tabular-nums text-muted-foreground">
                                {trace.duration_ms}ms
                              </span>
                              <Badge tone={trace.status === "SUCCEEDED" ? "success" : trace.status === "UNKNOWN" ? "neutral" : "destructive"}>
                                {trace.status}
                              </Badge>
                              <span className="text-muted-foreground group-open:hidden">▸</span>
                            </summary>
                            <pre className="mt-1.5 max-h-40 overflow-auto rounded-md border border-border bg-muted/30 p-2.5 font-mono text-[11px]">
                              {JSON.stringify({ sequence: frame.sequence, kind: frame.kind, payload: trace.payload }, null, 2)}
                            </pre>
                          </details>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </PermissionGate>
    </div>
  );
}
