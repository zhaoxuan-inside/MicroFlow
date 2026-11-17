/** 配置中心（Nacos 模式）：命名空间 → 配置项 → 版本历史 → 灰度发布（百分比分桶 + 白名单）。
 *
 * 全部走控制面 REST（orchClient :8200）：版本号由后端自增派生（保存即新草稿版本），
 * 灰度设置随发布提交；resolve 提供灰度命中试算（白名单直通 / sha256 分桶）。
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Field, Input, Modal, ModalActions, PageHeader, Select, Spinner, Textarea, diffLines, useToast } from "@microflow4kit/ui";
import { PermissionGate, useScope } from "../orchAuth";
import { orchDispatch } from "../orchClient";

interface Namespace {
  code: string;
  name: string;
  description: string;
  items: number;
  created_by?: string;
  created_at?: string;
}
interface GrayConfig {
  percent: number;
  whitelist: string[];
}
interface ItemRow {
  key: string;
  value_type: string;
  description: string;
  gray: GrayConfig | null;
  current_version: string;
  created_by?: string;
  updated_at?: string;
}
/** 弹窗内使用的最小定位信息：命名空间 + 配置键 + 展示上下文。 */
interface ItemRef {
  namespace: string;
  key: string;
  value_type: string;
  description: string;
  current_version: string;
  gray: GrayConfig | null;
}
interface HistoryRow {
  version: string;
  value: unknown;
  status: "DRAFT" | "PUBLISHED" | "ROLLED_BACK";
  note: string;
  published_by?: string | null;
  published_at?: string | null;
  created_by: string;
  created_at?: string;
}

const historyTone: Record<string, "neutral" | "success" | "warning"> = {
  DRAFT: "warning",
  PUBLISHED: "success",
  ROLLED_BACK: "neutral",
};

/** 版本 value → 编辑器文本：TEXT 原样，其余按 JSON 美化。 */
function formatValue(value: unknown, valueType: string): string {
  if (valueType !== "JSON" && typeof value === "string") return value;
  return JSON.stringify(value ?? (valueType === "JSON" ? {} : ""), null, 2);
}

function useValidateJson(valueType: string, content: string): string {
  return useMemo(() => {
    if (valueType !== "JSON") return "";
    try {
      JSON.parse(content);
      return "";
    } catch (e) {
      return `JSON 格式错误：${(e as Error).message}`;
    }
  }, [valueType, content]);
}

function itemPath(item: Pick<ItemRef, "namespace" | "key">, suffix = ""): string {
  return `/configcenter/namespaces/${encodeURIComponent(item.namespace)}/items/${encodeURIComponent(item.key)}${suffix}`;
}

export function ConfigsPage() {
  const { hasPermission } = useScope();
  const qc = useQueryClient();
  const canWrite = hasPermission("configcenter:write");

  const namespaces = useQuery({
    queryKey: ["config-namespaces"],
    queryFn: () => orchDispatch<{ namespaces: Namespace[] }>("GET", "/configcenter/namespaces"),
  });
  const [activeNs, setActiveNs] = useState("");
  const items = useQuery({
    queryKey: ["config-items", activeNs],
    queryFn: () => orchDispatch<{ items: ItemRow[] }>(
      "GET", `/configcenter/namespaces/${encodeURIComponent(activeNs)}/items`),
    enabled: Boolean(activeNs),
  });
  const [creatingNs, setCreatingNs] = useState(false);
  const [creatingItem, setCreatingItem] = useState(false);
  const [editingItem, setEditingItem] = useState<ItemRef | null>(null);
  const [publishingItem, setPublishingItem] = useState<ItemRef | null>(null);
  const [historyItem, setHistoryItem] = useState<ItemRef | null>(null);
  const [resolveItem, setResolveItem] = useState<ItemRef | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["config-namespaces"] });
    qc.invalidateQueries({ queryKey: ["config-items"] });
  };

  const nsRows = namespaces.data?.namespaces || [];
  const itemRows = items.data?.items || [];
  const toRef = (item: ItemRow): ItemRef => ({
    namespace: activeNs,
    key: item.key,
    value_type: item.value_type,
    description: item.description,
    current_version: item.current_version || "",
    gray: item.gray || null,
  });

  return (
    <div>
      <PageHeader
        title="配置中心"
        description="命名空间 → 配置项 → 版本历史 → 灰度发布（百分比分桶 + 白名单直通）"
        actions={
          <PermissionGate permission="configcenter:write">
            <Button className="h-8 text-xs" onClick={() => setCreatingNs(true)}>新建命名空间</Button>
            <Button variant="secondary" className="h-8 text-xs" onClick={() => setCreatingItem(true)} disabled={!nsRows.length}>
              新建配置项
            </Button>
          </PermissionGate>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <Card className="h-fit">
          <CardHeader><CardTitle>命名空间</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            {namespaces.isPending ? (
              <div className="flex justify-center py-8"><Spinner /></div>
            ) : !nsRows.length ? (
              <EmptyState title="暂无命名空间" />
            ) : (
              nsRows.map((ns) => (
                <button
                  key={ns.code}
                  type="button"
                  className={`w-full rounded-md px-2.5 py-2 text-left text-sm transition-colors ${
                    activeNs === ns.code ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground hover:bg-accent"
                  }`}
                  onClick={() => setActiveNs(activeNs === ns.code ? "" : ns.code)}
                >
                  <div className="font-medium">{ns.name}</div>
                  <div className="text-xs">{ns.code} · {ns.items} 项</div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          {namespaces.isPending || (activeNs && items.isPending) ? (
            <div className="flex justify-center py-16"><Spinner /></div>
          ) : !activeNs ? (
            <div className="p-5"><EmptyState title="请先选择命名空间" hint="配置项按命名空间隔离存放。" /></div>
          ) : !itemRows.length ? (
            <div className="p-5"><EmptyState title="暂无配置项" hint="创建配置项并保存草稿版本后，发布（可灰度）供宿主运行时解析生效值。" /></div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                  <th className="px-4 py-3 font-medium font-mono uppercase">配置项</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">类型</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">稳定版</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">灰度态</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">操作</th>
                </tr>
              </thead>
              <tbody>
                {itemRows.map((item) => (
                  <tr key={item.key} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                    <td className="px-4 py-3">
                      <div className="font-medium">{item.key}</div>
                      <div className="text-xs text-muted-foreground">{activeNs} / {item.key}{item.description ? ` · ${item.description}` : ""}</div>
                    </td>
                    <td className="px-4 py-3"><Badge>{item.value_type}</Badge></td>
                    <td className="px-4 py-3 text-muted-foreground">{item.current_version || "—"}</td>
                    <td className="px-4 py-3">
                      {item.gray && (item.gray.percent > 0 || (item.gray.whitelist || []).length) ? (
                        <Badge tone="warning">
                          灰度 {item.gray.percent}% · 白名单 {(item.gray.whitelist || []).length} 人
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <PermissionGate permission="configcenter:write">
                          <Button variant="secondary" className="h-7 text-xs"
                            onClick={() => setEditingItem(toRef(item))}>
                            编辑草稿
                          </Button>
                          <Button variant="secondary" className="h-7 text-xs"
                            onClick={() => setPublishingItem(toRef(item))}>
                            发布
                          </Button>
                        </PermissionGate>
                        <Button variant="ghost" className="h-7 text-xs" onClick={() => setHistoryItem(toRef(item))}>
                          历史
                        </Button>
                        <Button variant="ghost" className="h-7 text-xs" onClick={() => setResolveItem(toRef(item))}>
                          解析
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <CreateNamespaceModal open={creatingNs} onClose={() => setCreatingNs(false)} onCreated={(code) => { setCreatingNs(false); setActiveNs(code); refresh(); }} />
      <CreateItemModal
        open={creatingItem}
        namespaces={nsRows}
        defaultNamespace={activeNs}
        onClose={() => setCreatingItem(false)}
        onCreated={() => { setCreatingItem(false); refresh(); }}
      />
      {editingItem && (
        <EditDraftModal
          item={editingItem}
          onClose={() => { setEditingItem(null); refresh(); }}
        />
      )}
      {publishingItem && (
        <PublishModal
          item={publishingItem}
          canWrite={canWrite}
          onClose={() => { setPublishingItem(null); refresh(); }}
        />
      )}
      {historyItem && (
        <HistoryModal item={historyItem} canWrite={canWrite} onClose={() => { setHistoryItem(null); refresh(); }} />
      )}
      {resolveItem && (
        <ResolveModal item={resolveItem} onClose={() => setResolveItem(null)} />
      )}
    </div>
  );
}

function CreateNamespaceModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (code: string) => void }) {
  const { toast } = useToast();
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建命名空间"
      footer={
        <ModalActions onCancel={onClose} busy={busy}>
          <Button disabled={busy || !form.code} onClick={async () => {
            setBusy(true);
            try {
              await orchDispatch("POST", "/configcenter/namespaces/create", form);
              toast({ title: "命名空间已创建", tone: "success" });
              onCreated(form.code);
            } catch (err) {
              toast({ title: "创建失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
            } finally { setBusy(false); }
          }}>{busy ? "创建中…" : "创建"}</Button>
        </ModalActions>
      }
    >
      <div className="grid gap-3">
        <Field label="标识" hint="2-48 位小写字母/数字/下划线/横线，字母开头">
          <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="pricing" />
        </Field>
        <Field label="名称"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="描述"><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

function CreateItemModal({
  open, namespaces, defaultNamespace, onClose, onCreated,
}: {
  open: boolean;
  namespaces: Namespace[];
  defaultNamespace: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { toast } = useToast();
  const [form, setForm] = useState({ namespace: defaultNamespace, key: "", value_type: "JSON", description: "" });
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建配置项"
      description="创建后为空配置项：先「编辑草稿」保存版本内容，再发布（可灰度）供宿主运行时解析"
      width="max-w-2xl"
      footer={
        <ModalActions onCancel={onClose} busy={busy}>
          <Button disabled={busy || !form.namespace || !form.key} onClick={async () => {
            setBusy(true);
            try {
              await orchDispatch("POST",
                `/configcenter/namespaces/${encodeURIComponent(form.namespace)}/items/create`,
                { key: form.key, value_type: form.value_type, description: form.description });
              toast({ title: "配置项已创建", description: "下一步：编辑草稿保存版本内容", tone: "success" });
              onCreated();
            } catch (err) {
              toast({ title: "创建失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
            } finally { setBusy(false); }
          }}>{busy ? "创建中…" : "创建"}</Button>
        </ModalActions>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="命名空间">
          <Select value={form.namespace} onChange={(e) => setForm({ ...form, namespace: e.target.value })}>
            <option value="">选择命名空间</option>
            {namespaces.map((ns) => <option key={ns.code} value={ns.code}>{ns.name}（{ns.code}）</option>)}
          </Select>
        </Field>
        <Field label="配置键" hint="字母开头，仅字母/数字/下划线/点号/横线，长度 2-64">
          <Input value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} placeholder="discount_rate" />
        </Field>
        <Field label="类型">
          <Select value={form.value_type} onChange={(e) => setForm({ ...form, value_type: e.target.value })}>
            <option value="JSON">JSON</option>
            <option value="TEXT">TEXT</option>
          </Select>
        </Field>
        <Field label="描述">
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

function EditDraftModal({ item, onClose }: { item: ItemRef; onClose: () => void }) {
  const { toast } = useToast();
  const history = useQuery({
    queryKey: ["config-history", item.namespace, item.key],
    queryFn: () => orchDispatch<{ history: HistoryRow[] }>("GET", itemPath(item, "/history")),
  });
  const [content, setContent] = useState("");
  const [note, setNote] = useState("");
  const [prefilled, setPrefilled] = useState(false);
  const [busy, setBusy] = useState(false);
  const jsonError = useValidateJson(item.value_type, content);
  const latest = history.data?.history?.[0];

  // 以最新版本内容预填编辑器（最新为草稿则在其上续写，否则派生新草稿）
  useEffect(() => {
    if (prefilled || !history.isSuccess) return;
    setPrefilled(true);
    setContent(latest ? formatValue(latest.value, item.value_type) : item.value_type === "JSON" ? "{}" : "");
  }, [prefilled, history.isSuccess, latest, item.value_type]);

  const save = async () => {
    setBusy(true);
    try {
      // JSON 类型在客户端先解析为值对象（后端按 JSON 值校验存储）；TEXT 原样为字符串值
      const value = item.value_type === "JSON" ? JSON.parse(content) : content;
      const res = await orchDispatch<{ version: string; status: string }>(
        "POST", itemPath(item, "/versions"), { value, note: note || undefined });
      toast({ title: `草稿已保存（版本 ${res.version}）`, tone: "success" });
      onClose();
    } catch (err) {
      toast({ title: "保存失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally { setBusy(false); }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`编辑草稿 · ${item.namespace}/${item.key}`}
      description={`保存即生成新草稿版本（版本号后端自增）；当前稳定版 ${item.current_version || "—"}`}
      width="max-w-2xl"
      footer={
        <ModalActions onCancel={onClose} busy={busy}>
          <Button disabled={busy || Boolean(jsonError)} onClick={save}>{busy ? "保存中…" : "保存草稿"}</Button>
        </ModalActions>
      }
    >
      <div className="grid gap-3">
        <Field label={`内容（${item.value_type}）`} hint={jsonError || undefined}>
          <Textarea rows={8} className="font-mono text-xs" value={content} onChange={(e) => setContent(e.target.value)} />
        </Field>
        <Field label="变更说明">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="留空则记为空说明" />
        </Field>
      </div>
    </Modal>
  );
}

function PublishModal({ item, canWrite, onClose }: { item: ItemRef; canWrite: boolean; onClose: () => void }) {
  const { toast } = useToast();
  const history = useQuery({
    queryKey: ["config-history", item.namespace, item.key],
    queryFn: () => orchDispatch<{ history: HistoryRow[] }>("GET", itemPath(item, "/history")),
  });
  const [version, setVersion] = useState("");
  const [percent, setPercent] = useState(100);
  const [whitelist, setWhitelist] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = history.data?.history || [];

  // 默认选中待发布的草稿版本（无草稿则取最新版本）
  useEffect(() => {
    if (!history.isSuccess) return;
    const draft = rows.find((v) => v.status === "DRAFT");
    setVersion(draft?.version || rows[0]?.version || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.isSuccess]);

  return (
    <Modal
      open
      onClose={onClose}
      title={`发布 · ${item.namespace}/${item.key}`}
      description="灰度发布：命中百分比分桶或白名单的用户取新内容，其余取稳定版；全量发布即提升为稳定版"
      footer={
        <ModalActions onCancel={onClose} busy={busy}>
          <Button disabled={busy || !canWrite || !version} onClick={async () => {
            setBusy(true);
            try {
              await orchDispatch("POST", itemPath(item, "/publish"), {
                version,
                gray: { percent, whitelist: whitelist.split(/[\s,]+/).filter(Boolean) },
              });
              toast({ title: percent >= 100 ? "已全量发布" : "灰度发布已生效", tone: "success" });
              onClose();
            } catch (err) {
              toast({ title: "发布失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
            } finally { setBusy(false); }
          }}>{busy ? "发布中…" : "发布"}</Button>
        </ModalActions>
      }
    >
      <div className="grid gap-3">
        <Field label="版本">
          <Select value={version} onChange={(e) => setVersion(e.target.value)}>
            {rows.map((v) => (
              <option key={v.version} value={v.version}>{v.version}（{v.status}）</option>
            ))}
          </Select>
        </Field>
        <Field label="灰度百分比（100 = 全量）">
          <Input type="number" min={0} max={100} value={percent} onChange={(e) => setPercent(Number(e.target.value))} />
        </Field>
        <Field label="白名单 uid（逗号或空格分隔，直通灰度）">
          <Textarea rows={2} value={whitelist} onChange={(e) => setWhitelist(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

function HistoryModal({ item, canWrite, onClose }: { item: ItemRef; canWrite: boolean; onClose: () => void }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const history = useQuery({
    queryKey: ["config-history", item.namespace, item.key],
    queryFn: () => orchDispatch<{ history: HistoryRow[] }>("GET", itemPath(item, "/history")),
  });
  const [diffPair, setDiffPair] = useState<[string, string] | null>(null);
  const rows = history.data?.history || [];
  const stableVersion = item.current_version;
  const byVersion = Object.fromEntries(rows.map((v) => [v.version, v]));
  const diffText = useMemo(() => {
    if (!diffPair) return "";
    const left = byVersion[diffPair[0]] ? formatValue(byVersion[diffPair[0]].value, item.value_type) : "";
    const right = byVersion[diffPair[1]] ? formatValue(byVersion[diffPair[1]].value, item.value_type) : "";
    return diffLines(left, right)
      .map((row) => {
        if (row.kind === "same") return `  ${row.left ?? ""}`;
        if (row.kind === "removed") return `- ${row.left ?? ""}`;
        return `+ ${row.right ?? ""}`;
      })
      .join("\n");
  }, [diffPair, byVersion, item.value_type]);

  const rollback = async (version: string) => {
    try {
      await orchDispatch("POST", itemPath(item, "/rollback"), { version });
      toast({ title: `已回滚到 ${version}`, tone: "success" });
      qc.invalidateQueries({ queryKey: ["config-history"] });
      qc.invalidateQueries({ queryKey: ["config-items"] });
      onClose();
    } catch (err) {
      toast({ title: "回滚失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    }
  };

  return (
    <Modal open onClose={onClose} title={`版本历史 · ${item.namespace}/${item.key}`} width="max-w-2xl">
      <div className="space-y-2">
        {!rows.length ? (
          <EmptyState title="暂无版本" />
        ) : (
          rows.map((v) => (
            <div key={v.version} className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{v.version}</span>
                  <Badge tone={historyTone[v.status] || "neutral"}>{v.status}</Badge>
                  {stableVersion === v.version && <Badge tone="primary">稳定版</Badge>}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {v.note || "—"}
                  {v.published_by ? ` · 发布 ${v.published_by}` : v.created_by ? ` · 创建 ${v.created_by}` : ""}
                </div>
              </div>
              <div className="flex shrink-0 gap-1.5">
                {canWrite && stableVersion !== v.version && (
                  <Button variant="secondary" className="h-7 text-xs" onClick={() => rollback(v.version)}>回滚到此版</Button>
                )}
                <Button variant="ghost" className="h-7 text-xs"
                  onClick={() => setDiffPair(diffPair ? null : [v.version, stableVersion || v.version])}>
                  {diffPair?.[0] === v.version ? "收起对比" : "与稳定版对比"}
                </Button>
              </div>
            </div>
          ))
        )}
        {diffPair && (
          <Textarea readOnly rows={10} className="font-mono text-xs" value={diffText} />
        )}
      </div>
    </Modal>
  );
}

/** 灰度解析试算：给定 uid 实时解析命中通道（gray/stable）与生效版本。 */
function ResolveModal({ item, onClose }: { item: ItemRef; onClose: () => void }) {
  const [uid, setUid] = useState("");
  const resolve = useQuery({
    queryKey: ["config-resolve", item.namespace, item.key, uid],
    queryFn: () => orchDispatch<{ uid: string; version: string; channel: "gray" | "stable"; gray?: GrayConfig }>(
      "GET", `${itemPath(item, "/resolve")}?uid=${encodeURIComponent(uid)}`),
    enabled: Boolean(uid),
  });
  return (
    <Modal open onClose={onClose} title={`灰度解析 · ${item.namespace}/${item.key}`} description="输入 uid 实时解析生效版本与命中通道（白名单直通 / sha256 分桶）">
      <div className="space-y-3">
        <Field label="用户 uid">
          <Input value={uid} onChange={(e) => setUid(e.target.value)} placeholder="user_42" />
        </Field>
        {uid && (resolve.isPending ? (
          <div className="flex justify-center py-4"><Spinner /></div>
        ) : resolve.isError ? (
          <div className="text-xs text-destructive">{resolve.error instanceof Error ? resolve.error.message : "解析失败"}</div>
        ) : resolve.data ? (
          <div className="flex items-center gap-2 text-sm">
            <Badge tone={resolve.data.channel === "gray" ? "warning" : "primary"}>
              {resolve.data.channel === "gray" ? "灰度命中" : "稳定版"}
            </Badge>
            <span className="text-muted-foreground">生效版本</span>
            <span className="font-mono font-medium">{resolve.data.version || "—"}</span>
          </div>
        ) : null)}
      </div>
    </Modal>
  );
}
