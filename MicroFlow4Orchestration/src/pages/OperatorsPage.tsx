/** 算子目录：搜索 / 分页 / 复选框批量删除（被引用禁删）/ 详情跳转全页路由。
 *
 * 数据源：编排管理平台控制面（orchClient :8200）。
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  ModalActions,
  PageHeader,
  Select,
  Spinner,
  Textarea,
  cn,
  useToast,
} from "@microflow4kit/ui";
import { orchDispatch, getOrchToken } from "../orchClient";
import { CopyToProject } from "../components/CopyToProject";

interface OperatorRow {
  name: string;
  display_name: string;
  domain: string;
  description: string;
  source: string;
  source_env: string;
  current_version: string;
  referenced_count: number;
  referenced_by: string[];
  in_use: boolean;
  lock_status?: { holder?: string };
}

const SCRIPT_PLACEHOLDER = "async def action_entry(inputs, context):\n    return {'result': inputs.get('x', 0) * 2}";

export function OperatorsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();

  const list = useQuery({
    queryKey: ["orch-operators"],
    queryFn: () => orchDispatch<{ operators: OperatorRow[]; total: number }>("GET", "/operators"),
  });

  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [batchConfirm, setBatchConfirm] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);

  const all = list.data?.operators || [];
  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return all;
    return all.filter(
      (op) =>
        (op.name || "").toLowerCase().includes(kw) ||
        (op.display_name || "").toLowerCase().includes(kw) ||
        (op.domain || "").toLowerCase().includes(kw),
    );
  }, [all, q]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  useEffect(() => setPage(1), [q, pageSize]);
  useEffect(() => setChecked(new Set()), [safePage, q, pageSize]);

  const toggleOne = (name: string, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  };
  const toggleAll = (on: boolean) => {
    const deletable = pageRows.filter((op) => op.source !== "builtin" && !op.in_use);
    setChecked((prev) => {
      const next = new Set(prev);
      for (const op of deletable) {
        if (on) next.add(op.name);
        else next.delete(op.name);
      }
      return next;
    });
  };
  const allDeletableChecked = pageRows.filter((op) => op.source !== "builtin" && !op.in_use)
    .every((op) => checked.has(op.name));

  const batchDelete = async () => {
    setBatchRunning(true);
    let ok = 0;
    const failures: string[] = [];
    for (const name of checked) {
      try {
        await orchDispatch("DELETE", `/operators/${encodeURIComponent(name)}`);
        ok += 1;
      } catch (err) {
        failures.push(`${name}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setBatchRunning(false);
    setChecked(new Set());
    setBatchConfirm(false);
    qc.invalidateQueries({ queryKey: ["orch-operators"] });
    toast({
      title: `批量删除完成（成功 ${ok}/${checked.size}）`,
      description: failures.length ? failures.join("；") : undefined,
      tone: failures.length ? "warning" : "success",
    });
  };

  const singleDelete = async (name: string) => {
    try {
      await orchDispatch("DELETE", `/operators/${encodeURIComponent(name)}`);
      toast({ title: "算子已删除", tone: "success" });
      qc.invalidateQueries({ queryKey: ["orch-operators"] });
    } catch (err) {
      toast({ title: "删除失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    }
  };

  const [form, setForm] = useState({ name: "", display_name: "", domain: "custom", description: "" });
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await orchDispatch("POST", "/operators/create", {
        name: form.name, display_name: form.display_name || form.name,
        domain: form.domain || "custom", description: form.description,
      });
      if (code.trim()) {
        await orchDispatch("POST", `/operators/${encodeURIComponent(form.name)}/versions`, {
          code, changelog: "初始版本",
        });
      }
      toast({ title: "算子已创建（草稿）", tone: "success" });
      setCreating(false);
      setForm({ name: "", display_name: "", domain: "custom", description: "" });
      setCode("");
      qc.invalidateQueries({ queryKey: ["orch-operators"] });
    } catch (err) {
      toast({ title: "创建失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const selectedCount = checked.size;
  void allDeletableChecked;

  return (
    <div className="space-y-4">
      <PageHeader
        title="算子目录"
        description="契约化算子注册表：业务容器注册上报 + 平台登记；详情展示代码逻辑与被引用跳转"
        actions={<Button className="h-8 text-xs" onClick={() => setCreating(true)}>新建算子</Button>}
      />

      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-center gap-3 px-4 py-3">
          <Input
            placeholder="搜索名称 / 编码 / 域…"
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
          <div className="p-5"><EmptyState title="没有匹配的算子" hint="调整搜索关键词后重试。" /></div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left text-xs text-muted-foreground">
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox" aria-label="全选可删除项"
                      checked={pageRows.filter((op) => op.source !== "builtin" && !op.in_use).length > 0
                        && pageRows.filter((op) => op.source !== "builtin" && !op.in_use)
                          .every((op) => checked.has(op.name))}
                      onChange={(e) => toggleAll(e.target.checked)}
                    />
                  </th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">名称</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">当前版本</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">来源</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">被引用</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">锁定</th>
                  <th className="px-4 py-3 font-medium font-mono uppercase">操作</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((op) => {
                  const primary = op.display_name || op.name;
                  const deletable = op.source !== "builtin" && !op.in_use;
                  return (
                    <tr key={op.name} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                      <td className="w-10 px-3">
                        <input
                          type="checkbox" aria-label={`选择 ${op.name}`}
                          disabled={!deletable}
                          title={op.in_use ? "被引用的算子不能删除" : op.source === "builtin" ? "内置算子不可删除" : ""}
                          checked={checked.has(op.name)}
                          onChange={(e) => toggleOne(op.name, e.target.checked)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          className="block text-left font-medium text-primary hover:underline"
                          onClick={() => navigate(`/operators/${encodeURIComponent(op.name)}`)}
                        >
                          {primary}
                        </button>
                        {op.name !== primary && (
                          <div className="font-mono text-xs text-muted-foreground">{op.name}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{op.current_version || "—"}</td>
                      <td className="px-4 py-3">
                        <Badge tone={op.source === "builtin" ? "neutral" : "primary"}>
                          {op.source === "builtin" ? "内置" : op.source === "platform" ? "平台登记" : `容器(${op.source_env})`}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {op.referenced_count > 0 ? (
                          <span className="tabular-nums">{op.referenced_count} 处</span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn("text-xs", op.lock_status?.holder ? "text-warning" : "text-muted-foreground")}>
                          {op.lock_status?.holder ? `被 ${op.lock_status.holder} 锁定` : "空闲"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <Button variant="secondary" className="h-7 text-xs"
                            onClick={() => navigate(`/operators/${encodeURIComponent(op.name)}`)}>
                            详情
                          </Button>
                          <CopyToProject assetKind="operator" code={op.name} />
                          <Button
                            variant="secondary" className="h-7 text-xs"
                            disabled={!deletable}
                            title={op.in_use ? "被引用的算子不能删除" : op.source === "builtin" ? "内置算子不可删除" : ""}
                            onClick={() => singleDelete(op.name)}
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
        title="新建算子"
        description="创建后处于草稿态；单元测试通过后才能发布到业务容器"
        footer={
          <ModalActions onCancel={() => setCreating(false)} busy={busy}>
            <Button disabled={busy || !form.name} onClick={create}>
              {busy ? "创建中…" : "创建"}
            </Button>
          </ModalActions>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="算子名" hint="字母开头，仅字母/数字/下划线/点号，长度 2-64">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="my_operator" />
          </Field>
          <Field label="显示名">
            <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Field>
          <Field label="域标签">
            <Input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} />
          </Field>
          <Field label="描述">
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="初始脚本（可留空稍后在详情页填写）" className="sm:col-span-2">
            <Textarea rows={8} className="font-mono text-xs" value={code} onChange={(e) => setCode(e.target.value)} placeholder={SCRIPT_PLACEHOLDER} />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={batchConfirm}
        title="批量删除算子"
        description={`确认删除选中的 ${selectedCount} 个算子？被引用或内置算子会被后端拒绝并逐条报告。`}
        onConfirm={batchDelete}
        onCancel={() => setBatchConfirm(false)}
      />
    </div>
  );
}
