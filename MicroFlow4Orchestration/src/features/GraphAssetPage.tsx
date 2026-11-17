/** 图类资产（子图/场景）列表页：搜索 / 分页 / 复选框批量删除（守卫差异见下）/
 * 名称去重 / 详情跳全页路由。
 *
 * 数据源：编排管理平台控制面（orchClient :8200）。
 * 删除守卫：子图被场景引用时禁删（in_use）；场景已下发生产环境时禁删（deployed_envs）。
 * 全页详情路由：/subgraphs/:code、/scenarios/:code（GraphAssetDetailPage）。
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  ModalActions,
  PageHeader,
  Select,
  Spinner,
  useToast,
} from "@microflow4kit/ui";
import { orchDispatch } from "../orchClient";

type AssetKind = "subgraph" | "scenario";

interface SubgraphRow {
  code: string;
  display_name: string;
  description: string;
  current_version: string;
  referenced_count: number;
  referenced_by: string[];
  in_use: boolean;
}

interface ScenarioRow {
  code: string;
  display_name: string;
  description: string;
  current_version: string;
  deployed_envs: string[];
}

const KIND_LABEL: Record<AssetKind, string> = { subgraph: "子图", scenario: "场景" };
const STAGE_LABEL: Record<string, string> = {
  dev: "开发", test: "测试", staging: "预发", online: "生产",
};

export function GraphAssetPage({ assetKind }: { assetKind: AssetKind }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();

  const base = assetKind === "subgraph" ? "/subgraphs" : "/scenarios";
  const list = useQuery({
    queryKey: ["orch-graph-assets", assetKind],
    queryFn: () =>
      orchDispatch<{ subgraphs?: SubgraphRow[]; scenarios?: ScenarioRow[]; total: number }>(
        "GET", assetKind === "subgraph" ? "/subgraphs" : "/scenarios"),
  });
  const rows = ((list.data?.[assetKind === "subgraph" ? "subgraphs" : "scenarios"] || []) as Array<
    SubgraphRow & ScenarioRow
  >);

  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [batchConfirm, setBatchConfirm] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return rows;
    return rows.filter(
      (r) =>
        (r.code || "").toLowerCase().includes(kw) ||
        (r.display_name || "").toLowerCase().includes(kw),
    );
  }, [rows, q]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  useEffect(() => setPage(1), [q, pageSize]);
  useEffect(() => setChecked(new Set()), [safePage, q, pageSize]);

  const deletableOf = (row: SubgraphRow & ScenarioRow): string | null => {
    if (assetKind === "subgraph" && row.in_use) return "被场景引用的子图不能删除";
    if (assetKind === "scenario" && (row.deployed_envs || []).includes("online"))
      return "已下发生产环境的场景不能删除";
    return null;
  };

  const toggleOne = (code: string, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(code);
      else next.delete(code);
      return next;
    });
  };
  const deletableRows = pageRows.filter((r) => !deletableOf(r));
  const toggleAll = (on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      for (const r of deletableRows) {
        if (on) next.add(r.code);
        else next.delete(r.code);
      }
      return next;
    });
  };

  const runDelete = async (codes: string[]) => {
    let ok = 0;
    const failures: string[] = [];
    for (const code of codes) {
      try {
        await orchDispatch("DELETE", `${base}/${encodeURIComponent(code)}`);
        ok += 1;
      } catch (err) {
        failures.push(`${code}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setChecked(new Set());
    qc.invalidateQueries({ queryKey: ["orch-graph-assets", assetKind] });
    return { ok, failures };
  };

  const batchDelete = async () => {
    setBatchRunning(true);
    const { ok, failures } = await runDelete([...checked]);
    setBatchRunning(false);
    setBatchConfirm(false);
    toast({
      title: `批量删除完成（成功 ${ok}/${checked.size}）`,
      description: failures.length ? failures.join("；") : undefined,
      tone: failures.length ? "warning" : "success",
    });
  };

  const singleDelete = async (code: string) => {
    const { failures } = await runDelete([code]);
    if (failures.length) {
      toast({ title: "删除失败", description: failures[0], tone: "destructive" });
    } else {
      toast({ title: `${KIND_LABEL[assetKind]}已删除`, tone: "success" });
    }
  };

  const [form, setForm] = useState({ code: "", display_name: "", description: "" });
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await orchDispatch("POST", `${base}/create`, {
        code: form.code, display_name: form.display_name || form.code, description: form.description,
      });
      toast({ title: `${KIND_LABEL[assetKind]}已创建（草稿）`, tone: "success" });
      setCreating(false);
      setForm({ code: "", display_name: "", description: "" });
      qc.invalidateQueries({ queryKey: ["orch-graph-assets", assetKind] });
      navigate(`${base}/${encodeURIComponent(form.code)}`);
    } catch (err) {
      toast({ title: "创建失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const selectedCount = checked.size;

  return (
    <div className="space-y-4">
      <PageHeader
        title={assetKind === "subgraph" ? "子图目录" : "场景目录"}
        description={
          assetKind === "subgraph"
            ? "把已发布算子编排成可复用子流水线；被场景引用期间禁止删除"
            : "算子与子图混合编排；经 开发→测试→预发→生产 四阶段下发，阶段不可跳过"
        }
        actions={<Button className="h-8 text-xs" onClick={() => setCreating(true)}>新建{KIND_LABEL[assetKind]}</Button>}
      />

      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 px-4 py-3">
          <Input
            placeholder={`搜索${KIND_LABEL[assetKind]}编码 / 显示名…`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-8 max-w-xs text-xs"
          />
          <span className="ml-auto text-xs tabular-nums text-muted-foreground">共 {filtered.length} 条</span>
          {selectedCount > 0 && (
            <Button variant="destructive" className="h-8 text-xs" onClick={() => setBatchConfirm(true)}>
              批量删除（{selectedCount}）
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="mb-4">
        {list.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : !filtered.length ? (
          <div className="p-5">
            <EmptyState title={`没有匹配的${KIND_LABEL[assetKind]}`} hint="调整搜索关键词或新建一条。" />
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox" aria-label="全选可删除项"
                      checked={deletableRows.length > 0 && deletableRows.every((r) => checked.has(r.code))}
                      onChange={(e) => toggleAll(e.target.checked)}
                    />
                  </th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">名称</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">当前版本</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">
                    {assetKind === "subgraph" ? "被引用" : "已下发环境"}
                  </th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">操作</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row) => {
                  const primary = row.display_name || row.code;
                  const guard = deletableOf(row);
                  return (
                    <tr key={row.code} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                      <td className="w-10 px-3">
                        <input
                          type="checkbox" aria-label={`选择 ${row.code}`}
                          disabled={Boolean(guard)}
                          title={guard || ""}
                          checked={checked.has(row.code)}
                          onChange={(e) => toggleOne(row.code, e.target.checked)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          className="block text-left font-medium text-primary hover:underline"
                          onClick={() => navigate(`${base}/${encodeURIComponent(row.code)}`)}
                        >
                          {primary}
                        </button>
                        {row.code !== primary && (
                          <div className="font-mono text-xs text-muted-foreground">{row.code}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{row.current_version || "—"}</td>
                      <td className="px-4 py-3">
                        {assetKind === "subgraph" ? (
                          row.referenced_count > 0 ? (
                            <span className="tabular-nums">{row.referenced_count} 处</span>
                          ) : "—"
                        ) : (row.deployed_envs || []).length ? (
                          <div className="flex flex-wrap gap-1">
                            {row.deployed_envs.map((env) => (
                              <Badge key={env} tone={env === "online" ? "success" : "neutral"}>
                                {STAGE_LABEL[env] || env}
                              </Badge>
                            ))}
                          </div>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <Button variant="secondary" className="h-7 text-xs"
                            onClick={() => navigate(`${base}/${encodeURIComponent(row.code)}`)}>
                            详情
                          </Button>
                          <Button
                            variant="secondary" className="h-7 text-xs"
                            disabled={Boolean(guard)}
                            title={guard || ""}
                            onClick={() => singleDelete(row.code)}
                          >
                            删除
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-xs text-muted-foreground">
              <span className="tabular-nums">第 {safePage} / {totalPages} 页 · 共 {filtered.length} 条</span>
              <div className="flex items-center gap-2">
                每页
                <Select aria-label="每页条数" className="h-7 w-20 text-xs" value={String(pageSize)}
                  onChange={(e) => setPageSize(Number(e.target.value))}>
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                </Select>
                <Button variant="secondary" className="h-7 px-2 text-xs" disabled={safePage <= 1}
                  onClick={() => setPage(safePage - 1)}>上一页</Button>
                <Button variant="secondary" className="h-7 px-2 text-xs" disabled={safePage >= totalPages}
                  onClick={() => setPage(safePage + 1)}>下一页</Button>
              </div>
            </div>
          </>
        )}
      </Card>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={`新建${KIND_LABEL[assetKind]}`}
        description="创建后处于草稿态；在详情页画布编排并保存版本"
        footer={
          <ModalActions onCancel={() => setCreating(false)} busy={busy}>
            <Button disabled={busy || !form.code} onClick={create}>
              {busy ? "创建中…" : "创建"}
            </Button>
          </ModalActions>
        }
      >
        <div className="grid gap-3">
          <Field label="编码" hint="字母开头，仅字母/数字/下划线/横线，长度 3-64">
            <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder={assetKind === "subgraph" ? "MY_SUBFLOW" : "MY_FLOW"} />
          </Field>
          <Field label="显示名">
            <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Field>
          <Field label="描述">
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={batchConfirm}
        title={`批量删除${KIND_LABEL[assetKind]}`}
        description={
          assetKind === "subgraph"
            ? `确认删除选中的 ${selectedCount} 个子图？被场景引用的子图会被后端拒绝并逐条报告。`
            : `确认删除选中的 ${selectedCount} 个场景？已下发生产环境的场景会被后端拒绝并逐条报告。`
        }
        onConfirm={batchDelete}
        onCancel={() => setBatchConfirm(false)}
      />
    </div>
  );
}
