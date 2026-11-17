/** 子图/场景全页详情：元信息 / 编排画布（只读预览 + 编辑草稿工作区）/
 * 版本阶段进度（dev→test→staging→online）/ 下发推进 / E2E 执行 / 引用。
 *
 * 编辑流程：先取排他编辑锁（POST /scenarios|subgraphs/{code}/lock，15 分钟 TTL，
 * 编辑期间自动续期）→ 画布编辑（成环拒绝/撤销由 GraphEditor 承担）→
 * 保存新版本（POST .../versions，版本号由后端自增派生）→ 退出时释放锁。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Field, Input, PageHeader, Spinner, useToast } from "@microflow4kit/ui";
import { PermissionGate, useScope } from "../orchAuth";
import { orchDispatch, getOrchToken } from "../orchClient";
import { GraphEditor, type EditorGraph, type PaletteItem } from "../features/GraphEditor";

interface VersionRow {
  version: string;
  graph: EditorGraph;
  enable_saga?: boolean;
  changelog: string;
  created_by: string;
}
interface AssetDetail {
  code: string;
  display_name: string;
  description: string;
  current_version: string;
  referenced_by?: string[];
  referenced_count?: number;
  versions: VersionRow[];
  deployments: Record<string, string[]>;
}

const STAGES = ["dev", "test", "staging", "online"];
const STAGE_LABEL: Record<string, string> = {
  dev: "开发", test: "测试", staging: "预发", online: "生产",
};

function emptyGraph(): EditorGraph {
  return { entry_node: "", exit_node: "", nodes: [], edges: [] };
}

export function GraphAssetDetailPage({ assetKind }: { assetKind: "subgraph" | "scenario" }) {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { hasPermission, user } = useScope();
  const canWrite = hasPermission("orchestration:write");
  const myEmail = user?.email || "";

  const detail = useQuery({
    queryKey: ["orch-graph-asset", assetKind, code, getOrchToken()],
    queryFn: () => orchDispatch<AssetDetail>(
      "GET",
      assetKind === "subgraph"
        ? `/subgraphs/${encodeURIComponent(code)}`
        : `/scenarios/${encodeURIComponent(code)}`,
    ),
    enabled: Boolean(getOrchToken()) && Boolean(code),
  });
  const asset = detail.data;

  const base = assetKind === "subgraph" ? "/subgraphs" : "/scenarios";
  const lockPath = `${base}/${encodeURIComponent(code)}/lock`;

  // ---------------------------------------------------------------------------
  // 编辑草稿工作区：锁 → 画布编辑 → 保存新版本
  // ---------------------------------------------------------------------------
  const [editing, setEditing] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [draft, setDraft] = useState<EditorGraph>(emptyGraph);
  const [saga, setSaga] = useState(true);
  const [changelog, setChangelog] = useState("");
  const [saving, setSaving] = useState(false);
  const editingRef = useRef(editing);
  editingRef.current = editing;

  // 切换资产（路由参数变化）时退出编辑态，避免把草稿带到另一个资产
  useEffect(() => { setEditing(false); }, [code]);

  // 卸载时若仍持锁则释放，避免 15 分钟 TTL 空占
  useEffect(() => {
    return () => {
      if (editingRef.current) {
        orchDispatch("DELETE", lockPath).catch(() => { /* 释放失败由 TTL 兜底 */ });
      }
    };
  }, [lockPath]);

  // 持锁编辑期间每 10 分钟自动续期（锁 TTL 15 分钟）
  useEffect(() => {
    if (!editing) return;
    const timer = setInterval(() => {
      orchDispatch("POST", lockPath, {}).catch(() => { /* 续期失败不中断编辑，保存时后端会再校验 */ });
    }, 10 * 60 * 1000);
    return () => clearInterval(timer);
  }, [editing, lockPath]);

  const enterEdit = async () => {
    setLockBusy(true);
    try {
      await orchDispatch("POST", lockPath, {});
      const latest = asset?.versions?.[0];
      const graph = latest?.graph;
      setDraft(graph ? { ...emptyGraph(), ...JSON.parse(JSON.stringify(graph)) } : emptyGraph());
      setSaga(latest?.enable_saga ?? graph?.enable_saga_compensation ?? true);
      setChangelog("");
      setEditing(true);
    } catch (err) {
      toast({ title: "获取编辑锁失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setLockBusy(false);
    }
  };

  const exitEdit = async () => {
    try { await orchDispatch("DELETE", lockPath); } catch { /* 忽略 */ }
    setEditing(false);
    detail.refetch();
  };

  const saveVersion = async () => {
    if (!draft.nodes.length) {
      toast({ title: "画布至少需要一个节点", tone: "warning" });
      return;
    }
    setSaving(true);
    try {
      // 拖拽位置缓存（_x/_y）仅前端呈现用，不入库
      const nodes = draft.nodes.map(({ _x: _x, _y: _y, ...rest }) => rest);
      const graph: EditorGraph = {
        entry_node: draft.entry_node,
        exit_node: draft.exit_node,
        nodes,
        edges: draft.edges,
      };
      if (assetKind === "scenario") graph.enable_saga_compensation = saga;
      const body: Record<string, unknown> = {
        graph,
        changelog: changelog || "更新编排",
      };
      if (assetKind === "scenario") body.enable_saga = saga;
      const r = await orchDispatch<{ code: string; version: string }>(
        "POST", `${base}/${encodeURIComponent(code)}/versions`, body);
      toast({ title: `已保存版本 ${r.version}`, description: "版本号由后端自增派生；未下发的草稿版本就地覆盖", tone: "success" });
      setChangelog("");
      qc.invalidateQueries({ queryKey: ["orch-graph-asset", assetKind, code] });
    } catch (err) {
      toast({ title: "保存失败", description: err instanceof Error ? err.message : String(err), tone: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  // 调色板：已发布/内置算子；场景额外引入其他子图（子图不可嵌套自身）
  const operators = useQuery({
    queryKey: ["orch-operators-palette"],
    queryFn: () => orchDispatch<{ operators: Array<{ name: string; display_name: string; domain: string; description: string; source: string; current_version: string }> }>("GET", "/operators"),
    enabled: Boolean(getOrchToken()),
  });
  const subgraphs = useQuery({
    queryKey: ["orch-subgraphs-palette"],
    queryFn: () => orchDispatch<{ subgraphs: Array<{ code: string; display_name: string; description: string; current_version: string }> }>("GET", "/subgraphs"),
    enabled: assetKind === "scenario" && Boolean(getOrchToken()),
  });
  const palette: PaletteItem[] = useMemo(() => {
    const items: PaletteItem[] = (operators.data?.operators || [])
      .filter((op) => op.source === "builtin" || op.current_version)
      .map((op) => ({
        kind: "OPERATOR" as const,
        key: op.name,
        label: op.display_name || op.name,
        domain: op.domain,
        description: op.description,
      }));
    if (assetKind === "scenario") {
      for (const row of subgraphs.data?.subgraphs || []) {
        if (row.code !== code && row.current_version) {
          items.push({
            kind: "SUBGRAPH" as const,
            key: row.code,
            label: row.display_name || row.code,
            description: row.description,
          });
        }
      }
    }
    return items;
  }, [operators.data, subgraphs.data, assetKind, code]);

  const latestGraph = useMemo<EditorGraph>(() => {
    const graph = asset?.versions?.[0]?.graph;
    return graph ? { ...emptyGraph(), ...graph } : emptyGraph();
  }, [asset]);

  // ---------------------------------------------------------------------------
  // 阶段下发推进
  // ---------------------------------------------------------------------------
  const [deploying, setDeploying] = useState("");
  const [deployMsg, setDeployMsg] = useState<string | null>(null);

  const deployments = asset?.deployments || {};
  const currentVersion = asset?.current_version || "";
  const deployedEnvsOf = (version: string) => deployments[version] || [];
  const nextStage = (version: string): string | null => {
    const envs = deployedEnvsOf(version);
    for (const stage of STAGES) {
      if (!envs.includes(stage)) return stage;
    }
    return null; // 全部阶段已下发
  };
  const canPromote = (version: string) => {
    const envs = deployedEnvsOf(version);
    if (!envs.length) return canWrite && currentVersion === version ? { ok: true, env: "dev" as const } : { ok: false };
    const last = STAGES.filter((s) => envs.includes(s)).sort(
      (a, b) => STAGES.indexOf(b) - STAGES.indexOf(a))[0];
    const idx = STAGES.indexOf(last);
    if (idx >= STAGES.length - 1) return { ok: false };
    // 不可跳过：只能推进到紧邻下一阶段
    return canWrite ? { ok: true, env: STAGES[idx + 1] } : { ok: false };
  };

  const deploy = async (version: string, env: string) => {
    setDeploying(env);
    setDeployMsg(null);
    try {
      const r = await orchDispatch<{ deployed: boolean; error?: string }>(
        "POST", `/scenarios/${encodeURIComponent(code)}/deploy`, { version, env });
      setDeployMsg(r.deployed ? `已下发到 ${env}` : `下发失败：${r.error || ""}`);
      qc.invalidateQueries({ queryKey: ["orch-graph-asset", assetKind, code] });
    } catch (err) {
      setDeployMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setDeploying("");
    }
  };

  // E2E：经控制面转发对应环境容器执行（真实业务数据路径）
  const [executing, setExecuting] = useState(false);
  const [execMsg, setExecMsg] = useState<string | null>(null);
  const runE2E = async (env: string) => {
    setExecuting(true);
    setExecMsg(null);
    try {
      const r = await orchDispatch<{ status: string }>(
        "POST", `/scenarios/${encodeURIComponent(code)}/execute`, { env, inputs: {} });
      setExecMsg(`${env} 环境执行：${r.status}`);
    } catch (err) {
      setExecMsg(`执行失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setExecuting(false);
    }
  };

  if (!getOrchToken() || !user) {
    return (
      <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
        会话已失效，请先登录编排管理平台。
      </CardContent></Card>
    );
  }
  if (detail.isPending) {
    return <div className="flex justify-center py-16"><Spinner /></div>;
  }
  if (detail.isError || !asset) {
    return (
      <div>
        <PageHeader title={`${assetKind === "subgraph" ? "子图" : "场景"} ${code}`} description="详情加载失败"
          actions={<Button variant="secondary" onClick={() => navigate(assetKind === "subgraph" ? "/subgraphs" : "/scenarios")}>返回列表</Button>} />
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          {detail.error instanceof Error ? detail.error.message : "资产不存在或不可见"}
        </CardContent></Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={asset.display_name || code}
        description={asset.description || (assetKind === "subgraph" ? "可复用的复合编排" : "对外发布的业务流程")}
        actions={<Button variant="secondary" onClick={() => navigate(assetKind === "subgraph" ? "/subgraphs" : "/scenarios")}>返回列表</Button>}
      />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-muted-foreground">{code}</span>
        {currentVersion && <Badge tone="primary">当前 {currentVersion}</Badge>}
      </div>

      {/* 编排画布：只读预览 + 编辑草稿工作区 */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>编排画布{editing ? "（编辑草稿）" : "（当前版本只读）"}</CardTitle>
            <div className="flex items-center gap-2">
              {!editing ? (
                <PermissionGate permission="orchestration:write">
                  <Button className="h-7 text-xs" disabled={lockBusy} onClick={enterEdit}>
                    {lockBusy ? "取锁中…" : "编辑草稿"}
                  </Button>
                </PermissionGate>
              ) : (
                <>
                  <span className="text-xs text-muted-foreground">
                    已持编辑锁{myEmail ? `（${myEmail}）` : ""} · 15 分钟 TTL，编辑期间自动续期
                  </span>
                  <Button variant="secondary" className="h-7 text-xs" onClick={exitEdit}>
                    退出编辑
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <GraphEditor
            graph={editing ? draft : latestGraph}
            editable={editing}
            allowSubgraphs={assetKind === "scenario"}
            palette={palette}
            onChange={setDraft}
          />
          {editing ? (
            <div className="flex flex-wrap items-end gap-3">
              {assetKind === "scenario" && (
                <label className="flex items-center gap-2 pb-2 text-sm text-muted-foreground">
                  <input type="checkbox" checked={saga} onChange={(e) => setSaga(e.target.checked)} />
                  启用 Saga 补偿（节点失败时按逆序触发补偿语义）
                </label>
              )}
              <Field label="变更说明" className="min-w-48 flex-1">
                <Input value={changelog} onChange={(e) => setChangelog(e.target.value)} placeholder="留空则沿用默认说明" />
              </Field>
              <Button className="h-9" disabled={saving} onClick={saveVersion}>
                {saving ? "保存中…" : "保存新版本"}
              </Button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              点击「编辑草稿」获取排他编辑锁后修改画布；保存新版本的版本号由后端自增派生（未下发过的草稿版本就地覆盖）。
            </p>
          )}
        </CardContent>
      </Card>

      {/* 版本与阶段进度 */}
      <Card>
        <CardHeader><CardTitle>版本与阶段下发进度（dev → test → staging → online，不可跳过）</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {(asset.versions || []).map((v) => {
            const envs = deployedEnvsOf(v.version);
            const promote = canPromote(v.version);
            return (
              <div key={v.version} className="rounded-md border border-border/70 px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium font-mono">{v.version}</span>
                    {currentVersion === v.version && <Badge tone="primary">当前</Badge>}
                    {envs.map((env) => <Badge key={env} tone="success">{STAGE_LABEL[env] || env}</Badge>)}
                  </div>
                  {canWrite && promote.ok && promote.env && (
                    <Button
                      variant="secondary" className="h-7 text-xs"
                      disabled={deploying === promote.env}
                      onClick={() => deploy(v.version, promote.env)}
                    >
                      {deploying === promote.env ? "下发中…" : `下发到 ${STAGE_LABEL[promote.env] || promote.env}`}
                    </Button>
                  )}
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">{v.changelog || "—"} · {v.created_by}</div>
              </div>
            );
          })}
          {deployMsg && <div className="text-xs text-muted-foreground">{deployMsg}</div>}
        </CardContent>
      </Card>

      {/* E2E 执行（场景） */}
      {assetKind === "scenario" && (
        <Card>
          <CardHeader><CardTitle>端到端执行（真实业务数据路径；开启 debug 后逐算子 I/O 上报控制面）</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              {STAGES.filter((env) => deployedEnvsOf(currentVersion).includes(env)).map((env) => (
                <Button key={env} variant="secondary" className="h-7 text-xs" disabled={executing}
                  onClick={() => runE2E(env)}>
                  {executing ? "执行中…" : `执行 E2E（${STAGE_LABEL[env] || env}）`}
                </Button>
              ))}
            </div>
            {execMsg && <div className="text-xs text-muted-foreground">{execMsg}</div>}
            <p className="text-xs text-muted-foreground">
              E2E 通过记录是推进到下一阶段的门禁（控制面强制校验）。
            </p>
          </CardContent>
        </Card>
      )}

      {/* 被引用（子图） */}
      {assetKind === "subgraph" && (
        <Card>
          <CardHeader>
            <CardTitle>被引用（{asset.referenced_count ?? (asset.referenced_by || []).length}）——点击跳转到对应场景</CardTitle>
          </CardHeader>
          <CardContent>
            {(asset.referenced_by || []).length ? (
              <ul className="space-y-1.5 text-xs">
                {(asset.referenced_by || []).map((ref) => {
                  const m = ref.match(/场景\s+(.+?)@/);
                  return m ? (
                    <li key={ref}>
                      <Link to={`/scenarios/${encodeURIComponent(m[1])}`} className="font-mono text-primary hover:underline">{ref}</Link>
                    </li>
                  ) : (
                    <li key={ref} className="font-mono">{ref}</li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">暂无被引用记录。</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
