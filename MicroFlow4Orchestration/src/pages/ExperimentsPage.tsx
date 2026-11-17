/** 实验管理（A/B）：创建（变体+权重+流量）→ 状态机（启动/停止/归档）→ 分流试算 → 读出。
 *
 * 全部走控制面 REST（orchClient :8200）；分桶 sha256(key:uid) 确定性，
 * 分派记录持久化在控制面（粘性分配），读出为真实分派分布。
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Field, Input, Modal, ModalActions, PageHeader, Select, Spinner, useToast } from "@microflow4kit/ui";
import { PermissionGate, useScope } from "../orchAuth";
import { orchDispatch } from "../orchClient";

const statusTone: Record<string, "neutral" | "success" | "warning" | "destructive" | "primary"> = {
  DRAFT: "warning",
  RUNNING: "success",
  STOPPED: "neutral",
  ARCHIVED: "neutral",
};

interface Variant {
  key: string;
  weight: number;
}

interface Experiment {
  key: string;
  display_name: string;
  description: string;
  status: string;
  traffic_percent: number;
  variants: Variant[];
  env_key: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

interface Readout {
  key: string;
  status: string;
  total: number;
  variants: Array<{ variant: string; assigned: number; share: number }>;
  note: string;
}

export function ExperimentsPage() {
  const { hasPermission } = useScope();
  const { toast } = useToast();
  const qc = useQueryClient();
  const canManage = hasPermission("experiment:manage");

  const list = useQuery({
    queryKey: ["experiments"],
    queryFn: () => orchDispatch<{ experiments: Experiment[] }>("GET", "/experiments"),
  });
  const [selected, setSelected] = useState("");
  const [creating, setCreating] = useState(false);

  const detail = useQuery({
    queryKey: ["experiment", selected],
    queryFn: () => orchDispatch<Experiment>("GET", `/experiments/${encodeURIComponent(selected)}`),
    enabled: Boolean(selected),
  });
  const readout = useQuery({
    queryKey: ["experiment-readout", selected],
    queryFn: () => orchDispatch<Readout>("GET", `/experiments/${encodeURIComponent(selected)}/readout`),
    enabled: Boolean(selected),
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["experiments"] });
    qc.invalidateQueries({ queryKey: ["experiment"] });
    qc.invalidateQueries({ queryKey: ["experiment-readout"] });
  };

  const setStatus = async (key: string, status: string) => {
    try {
      await orchDispatch("POST", `/experiments/${encodeURIComponent(key)}/status`, { status });
      toast({ title: `实验已${status === "RUNNING" ? "启动" : status === "STOPPED" ? "停止" : "归档"}`, tone: "success" });
      invalidateAll();
    } catch (err) {
      toast({ title: "状态变更失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    }
  };

  const remove = async (key: string) => {
    try {
      await orchDispatch("DELETE", `/experiments/${encodeURIComponent(key)}`);
      toast({ title: "实验已删除", tone: "success" });
      if (selected === key) setSelected("");
      invalidateAll();
    } catch (err) {
      toast({ title: "删除失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    }
  };

  const rows = list.data?.experiments || [];

  return (
    <div>
      <PageHeader
        title="实验管理"
        description="A/B 实验：确定性分桶 × 流量门控，粘性分配与真实结果读出"
        actions={
          <PermissionGate permission="experiment:manage">
            <Button className="h-8 text-xs" onClick={() => setCreating(true)}>
              新建实验
            </Button>
          </PermissionGate>
        }
      />

      <Card className="mb-4">
        {list.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : !rows.length ? (
          <div className="p-5">
            <EmptyState title="暂无实验" hint="创建实验后配置变体与流量，启动即对宿主客户端生效。" />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                <th className="px-5 py-3 font-medium font-mono uppercase">实验</th>
                <th className="px-5 py-3 font-medium font-mono uppercase">状态</th>
                <th className="px-5 py-3 font-medium font-mono uppercase">流量</th>
                <th className="px-5 py-3 font-medium font-mono uppercase">变体</th>
                <th className="px-5 py-3 font-medium font-mono uppercase">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.key} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                  <td className="px-5 py-3">
                    <div className="font-medium">{e.display_name}</div>
                    <div className="text-xs text-muted-foreground">{e.key}{e.description ? ` · ${e.description}` : ""}</div>
                  </td>
                  <td className="px-5 py-3"><Badge tone={statusTone[e.status] || "neutral"}>{e.status}</Badge></td>
                  <td className="px-5 py-3 tabular-nums text-muted-foreground">{e.traffic_percent}%</td>
                  <td className="px-5 py-3 text-muted-foreground">
                    {e.variants.map((v) => `${v.key}(${v.weight})`).join(" / ")}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Button variant="secondary" className="h-7 text-xs" onClick={() => setSelected(e.key)}>
                        详情
                      </Button>
                      <PermissionGate permission="experiment:manage">
                        {e.status === "DRAFT" && (
                          <Button className="h-7 text-xs" onClick={() => setStatus(e.key, "RUNNING")}>
                            启动
                          </Button>
                        )}
                        {e.status === "RUNNING" && (
                          <Button variant="secondary" className="h-7 text-xs" onClick={() => setStatus(e.key, "STOPPED")}>
                            停止
                          </Button>
                        )}
                        {e.status === "STOPPED" && (
                          <>
                            <Button className="h-7 text-xs" onClick={() => setStatus(e.key, "RUNNING")}>
                              恢复
                            </Button>
                            <Button variant="secondary" className="h-7 text-xs" onClick={() => setStatus(e.key, "ARCHIVED")}>
                              归档
                            </Button>
                          </>
                        )}
                        {e.status !== "RUNNING" && (
                          <Button variant="ghost" className="h-7 text-xs text-destructive" onClick={() => remove(e.key)}>
                            删除
                          </Button>
                        )}
                      </PermissionGate>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {selected && detail.data && (
        <ExperimentDetail
          experiment={detail.data}
          readout={readout.data}
          canManage={canManage}
          onChanged={invalidateAll}
          onClose={() => setSelected("")}
        />
      )}

      <CreateExperimentModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(key) => {
          setCreating(false);
          setSelected(key);
          qc.invalidateQueries({ queryKey: ["experiments"] });
        }}
      />
    </div>
  );
}

function ExperimentDetail({
  experiment,
  readout,
  canManage,
  onChanged,
  onClose,
}: {
  experiment: Experiment;
  readout?: Readout;
  canManage: boolean;
  onChanged: () => void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [tryUid, setTryUid] = useState("");
  const [tryResult, setTryResult] = useState<{ variant: string; in_experiment: boolean; reason?: string } | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>(
    () => Object.fromEntries(experiment.variants.map((v) => [v.key, v.weight])),
  );
  const [traffic, setTraffic] = useState(experiment.traffic_percent);
  const [saving, setSaving] = useState(false);

  const totalWeight = experiment.variants.reduce((s, v) => s + (weights[v.key] ?? v.weight), 0) || 1;
  // 运行中实验不可改变体集合（后端强制）：只允许调流量门控
  const variantsLocked = experiment.status === "RUNNING";

  const saveTuning = async () => {
    setSaving(true);
    try {
      await orchDispatch("POST", `/experiments/${encodeURIComponent(experiment.key)}/update`, {
        traffic_percent: traffic,
        ...(variantsLocked ? {} : {
          variants: experiment.variants.map((v) => ({ key: v.key, weight: weights[v.key] ?? v.weight })),
        }),
      });
      toast({ title: "变体权重与流量已更新", tone: "success" });
      onChanged();
    } catch (err) {
      toast({ title: "更新失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const tryAssign = async () => {
    try {
      const res = await orchDispatch<{ variant: string; in_experiment: boolean; reason?: string }>(
        "POST",
        `/experiments/${encodeURIComponent(experiment.key)}/assign`,
        { uid: tryUid },
      );
      setTryResult(res);
    } catch (err) {
      toast({ title: "试算失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">{experiment.display_name}</CardTitle>
            <div className="flex items-center gap-2">
              <Badge tone={statusTone[experiment.status] || "neutral"}>{experiment.status}</Badge>
              <Button variant="secondary" className="h-7 text-xs" onClick={onClose}>收起</Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            {experiment.key}{experiment.description ? ` · ${experiment.description}` : ""}
            {experiment.env_key ? ` · 生效环境 ${experiment.env_key}` : " · 全环境"}
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <PermissionGate permission="experiment:manage">
            <div className="space-y-2 rounded-md border border-border p-3">
              <div className="text-xs font-medium text-muted-foreground">
                变体权重与流量{variantsLocked ? "（运行中：变体锁定，只可调流量）" : ""}
              </div>
              {experiment.variants.map((v) => (
                <div key={v.key} className="flex items-center gap-3">
                  <Badge tone="primary">{v.key}</Badge>
                  <Input
                    type="number"
                    min={0}
                    step="0.1"
                    className="h-8 w-28 text-xs"
                    disabled={variantsLocked}
                    value={weights[v.key] ?? v.weight}
                    onChange={(e) => setWeights({ ...weights, [v.key]: Number(e.target.value) })}
                  />
                  <span className="text-xs text-muted-foreground">
                    归一化 {Math.round(((weights[v.key] ?? v.weight) / totalWeight) * 100)}%
                  </span>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground">流量门控</span>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  className="h-8 w-24 text-xs"
                  value={traffic}
                  onChange={(e) => setTraffic(Number(e.target.value))}
                />
                <span className="text-xs text-muted-foreground">%</span>
                <Button className="h-8 text-xs" disabled={saving || !canManage} onClick={saveTuning}>
                  {saving ? "保存中…" : "保存调优"}
                </Button>
              </div>
            </div>
          </PermissionGate>

          <div className="space-y-2 rounded-md border border-border p-3">
            <div className="text-xs font-medium text-muted-foreground">分流试算（sha256 稳定分桶，真实调用分配接口）</div>
            <div className="flex items-center gap-2">
              <Input
                className="h-8 max-w-xs text-xs"
                placeholder="用户 uid"
                value={tryUid}
                onChange={(e) => setTryUid(e.target.value)}
              />
              <Button variant="secondary" className="h-8 text-xs" disabled={!tryUid} onClick={tryAssign}>
                试算
              </Button>
              {tryResult && (
                <span className="text-xs">
                  {tryResult.in_experiment ? (
                    <>命中变体 <Badge tone="primary">{tryResult.variant}</Badge></>
                  ) : (
                    <span className="text-muted-foreground">未入实验（{tryResult.reason || "TRAFFIC"}）</span>
                  )}
                </span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>读出</CardTitle>
          <p className="text-xs text-muted-foreground">
            累计分配 {readout?.total ?? 0} 人；{readout?.note || "结果指标由宿主客户端经 outcome 上报后接入"}
          </p>
        </CardHeader>
        <CardContent>
          {!readout || !readout.variants.length ? (
            <EmptyState title="尚无分配记录" hint="实验启动后，宿主客户端的分流调用会在此聚合。" />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium font-mono uppercase">变体</th>
                  <th className="py-2 font-medium font-mono uppercase">分配数</th>
                  <th className="py-2 font-medium font-mono uppercase">占比</th>
                </tr>
              </thead>
              <tbody>
                {readout.variants.map((v) => (
                  <tr key={v.variant} className="border-b border-border/50 last:border-0">
                    <td className="py-2 font-medium">{v.variant}</td>
                    <td className="py-2">{v.assigned}</td>
                    <td className="py-2 text-muted-foreground">{Math.round((v.share ?? 0) * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function CreateExperimentModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (key: string) => void;
}) {
  const { toast } = useToast();
  const { activeEnvironments } = useScope();
  const [form, setForm] = useState({ key: "", display_name: "", description: "", traffic_percent: 100, env_key: "" });
  const [variants, setVariants] = useState<Variant[]>([
    { key: "control", weight: 1 },
    { key: "treatment", weight: 1 },
  ]);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      await orchDispatch("POST", "/experiments/create", {
        key: form.key,
        display_name: form.display_name || form.key,
        description: form.description,
        variants,
        traffic_percent: form.traffic_percent,
        env_key: form.env_key,
      });
      toast({ title: "实验已创建（草稿）", description: "启动后对宿主客户端生效", tone: "success" });
      onCreated(form.key);
    } catch (err) {
      toast({ title: "创建失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建实验"
      description="草稿态不参与分流；启动（RUNNING）后按流量门控对宿主客户端生效"
      footer={
        <ModalActions onCancel={onClose} busy={busy}>
          <Button disabled={busy || !form.key || variants.length < 1} onClick={create}>
            {busy ? "创建中…" : "创建"}
          </Button>
        </ModalActions>
      }
    >
      <div className="grid gap-3">
        <Field label="实验标识" hint="2-48 位小写字母/数字/下划线/横线，字母开头">
          <Input value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} placeholder="cta_color" />
        </Field>
        <Field label="名称">
          <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </Field>
        <Field label="描述">
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted-foreground">变体（权重为相对值）</div>
          <div className="space-y-2">
            {variants.map((v, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input
                  className="h-8 w-40 text-xs"
                  placeholder="变体键"
                  value={v.key}
                  onChange={(e) => setVariants(variants.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
                />
                <Input
                  type="number"
                  className="h-8 w-24 text-xs"
                  placeholder="权重"
                  value={v.weight}
                  onChange={(e) => setVariants(variants.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) } : x)))}
                />
                {variants.length > 1 && (
                  <Button variant="ghost" className="h-8 px-2 text-xs text-destructive"
                    onClick={() => setVariants(variants.filter((_, j) => j !== i))}>
                    ×
                  </Button>
                )}
              </div>
            ))}
          </div>
          <Button variant="secondary" className="mt-2 h-7 text-xs"
            onClick={() => setVariants([...variants, { key: `variant_${variants.length + 1}`, weight: 1 }])}>
            添加变体
          </Button>
        </div>
        <Field label="流量门控（%）" hint="命中桶 %100 < 流量百分比的用户进入实验">
          <Input type="number" min={0} max={100} value={form.traffic_percent}
            onChange={(e) => setForm({ ...form, traffic_percent: Number(e.target.value) })} />
        </Field>
        <Field label="生效环境" hint="宿主仅在匹配环境分流；留空由控制面按默认环境登记">
          <Select
            aria-label="选择生效环境"
            className="h-9 text-sm"
            value={form.env_key}
            onChange={(e) => setForm({ ...form, env_key: e.target.value })}
          >
            <option value="">默认（dev）</option>
            {activeEnvironments.map((env) => (
              <option key={env.key} value={env.key}>{env.name}{env.protected ? " 🔒" : ""}</option>
            ))}
          </Select>
        </Field>
      </div>
    </Modal>
  );
}
