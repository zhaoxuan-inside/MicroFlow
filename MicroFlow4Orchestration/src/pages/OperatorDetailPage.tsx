/** 算子全页详情：代码逻辑 / 引用清单跳转 / 单元测试卡 / 排他锁（控制面账号体系）。 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Field, Input, PageHeader, Spinner, Textarea } from "@microflow4kit/ui";
import { useScope } from "../orchAuth";
import { orchDispatch, getOrchToken } from "../orchClient";

interface OperatorVersion {
  version: string;
  code: string;
  entry_function: string;
  changelog: string;
  status: string;
  unit_test: string | null;
  created_by: string;
}
interface OperatorAsset {
  name: string;
  display_name: string;
  domain: string;
  description: string;
  source: string;
  source_env: string;
  current_version: string;
  referenced_by: string[];
  referenced_count: number;
  versions: OperatorVersion[];
}

/** 引用格式："子图 code@version" / "场景 code@version" → 跳转目标。 */
function parseRef(ref: string): { to: string } | null {
  const m = ref.match(/^(子图|场景)\s+(.+?)@/);
  if (!m) return null;
  const code = m[2];
  return m[1] === "子图"
    ? { to: `/subgraphs/${encodeURIComponent(code)}` }
    : { to: `/scenarios/${encodeURIComponent(code)}` };
}

export function OperatorDetailPage() {
  const { name = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, hasPermission, loading } = useScope();
  const myEmail = user?.email || "";
  const canWrite = hasPermission("orchestration:write");

  const detail = useQuery({
    queryKey: ["orch-operator", name, getOrchToken()],
    queryFn: () => orchDispatch<OperatorAsset>("GET", `/operators/${encodeURIComponent(name)}`),
    enabled: Boolean(getOrchToken()) && Boolean(name),
  });
  const asset = detail.data;
  const isCustom = Boolean(asset && asset.source !== "builtin");

  // 排他锁（控制面 /lock 端点；holder = 当前控制面账号邮箱）
  const [lockState, setLockState] = useState<{ holder: string; remaining_minutes: number } | null>(null);
  const refreshLock = async () => {
    try {
      const r = await orchDispatch<{ holder: string; remaining_minutes: number } | null>(
        "GET", `/operators/${encodeURIComponent(name)}/lock`);
      setLockState(r);
    } catch {
      setLockState(null);
    }
  };

  const acquireLock = async () => {
    try {
      const r = await orchDispatch<{ holder: string; remaining_minutes: number }>(
        "POST", `/operators/${encodeURIComponent(name)}/lock`);
      setLockState({ holder: r.holder, remaining_minutes: r.remaining_minutes ?? 15 });
    } catch (err) {
      setLockState({ holder: err instanceof Error ? err.message : String(err), remaining_minutes: 0 });
    }
  };
  const releaseLock = async () => {
    try { await orchDispatch("DELETE", `/operators/${encodeURIComponent(name)}/lock`); } catch { /* 忽略 */ }
    setLockState(null);
    detail.refetch();
  };

  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [changelog, setChangelog] = useState("");
  const [code, setCode] = useState("");
  const [saving, setSaving] = useState(false);
  const latestDraft = useMemo(
    () => [...(asset?.versions || [])].reverse().find((v) => v.status === "DRAFT"),
    [asset],
  );
  useEffect(() => {
    if (asset) {
      setDisplayName(asset.display_name || name);
      setDescription(asset.description || "");
      setCode(latestDraft?.code || "");
      void refreshLock();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset?.name, asset?.current_version]);

  const editable = Boolean(isCustom && canWrite && lockState?.holder === myEmail);

  const saveVersion = async () => {
    if (!code.trim()) return;
    setSaving(true);
    try {
      await orchDispatch("POST", `/operators/${encodeURIComponent(name)}/versions`, {
        code, display_name: displayName, description, changelog: changelog || "更新算子脚本",
      });
      setChangelog("");
      await detail.refetch();
      await refreshLock();
    } finally {
      setSaving(false);
    }
  };

  // 单元测试（对应环境容器执行真实算子代码）
  const [testInputs, setTestInputs] = useState("{}");
  const [testResult, setTestResult] = useState<{ status: string; output?: unknown; error?: string; duration_ms?: number } | null>(null);
  const [testing, setTesting] = useState(false);
  const testVersion = latestDraft?.version || asset?.current_version || "";
  const runUnitTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      let inputs: unknown = {};
      try { inputs = JSON.parse(testInputs || "{}"); } catch { throw new Error("测试输入 JSON 非法"); }
      const r = await orchDispatch<{ status: string; output?: unknown; error?: string; duration_ms?: number }>(
        "POST", `/operators/${encodeURIComponent(name)}/test`,
        { version: testVersion, inputs, env: "dev" });
      setTestResult(r);
      detail.refetch();
    } catch (err) {
      setTestResult({ status: "failed", error: err instanceof Error ? err.message : String(err) });
    } finally {
      setTesting(false);
    }
  };

  const publishVersion = async () => {
    await orchDispatch("POST", `/operators/${encodeURIComponent(name)}/publish`, { version: testVersion });
    detail.refetch();
  };

  if (loading) {
    return <div className="flex justify-center py-16"><Spinner /></div>;
  }
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
        <PageHeader title={`算子 ${name}`} description="详情加载失败"
          actions={<Button variant="secondary" onClick={() => navigate("/operators")}>返回列表</Button>} />
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          {detail.error instanceof Error ? detail.error.message : "算子不存在或不可见"}
        </CardContent></Card>
      </div>
    );
  }

  const versionRows = asset.versions || [];
  const referenced = asset.referenced_by || [];

  return (
    <div className="space-y-4">
      <PageHeader
        title={asset.display_name || name}
        description={asset.description || `${asset.domain} 域算子`}
        actions={<Button variant="secondary" onClick={() => navigate("/operators")}>返回算子目录</Button>}
      />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={asset.source === "builtin" ? "neutral" : "primary"}>
          {asset.source === "builtin" ? "内置" : asset.source === "platform" ? "平台登记" : `业务容器（${asset.source_env}）`}
        </Badge>
        <span className="font-mono text-muted-foreground">{name}</span>
        {asset.current_version && <span className="font-mono text-muted-foreground">· {asset.current_version}</span>}
      </div>

      {/* 代码逻辑 */}
      <Card>
        <CardHeader><CardTitle>代码逻辑</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {isCustom ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="显示名"><Input value={displayName} disabled={!editable} onChange={(e) => setDisplayName(e.target.value)} /></Field>
                <Field label="描述"><Input value={description} disabled={!editable} onChange={(e) => setDescription(e.target.value)} /></Field>
              </div>
              <Field label="算子脚本（入口 async def action_entry(inputs, context)）" hint="保存与发布均经过沙箱校验">
                <Textarea rows={10} className="font-mono text-xs" value={code} disabled={!editable} onChange={(e) => setCode(e.target.value)} />
              </Field>
              <div className="flex items-end gap-3">
                <Field label="变更说明" className="flex-1">
                  <Input value={changelog} disabled={!editable} onChange={(e) => setChangelog(e.target.value)} placeholder="留空则沿用默认说明" />
                </Field>
                <Button disabled={!editable || saving} onClick={saveVersion}>
                  {saving ? "保存中…" : "保存新版本"}
                </Button>
              </div>
              {!editable && (
                <p className="text-xs text-muted-foreground">
                  编辑需先获取排他锁
                  {lockState?.holder ? `（当前持锁：${lockState.holder}）` : "（当前无人持锁）"}。
                </p>
              )}
            </>
          ) : (
            <div className="text-sm text-muted-foreground">
              内置算子由业务容器注册上报，此处只读展示。
            </div>
          )}
        </CardContent>
      </Card>

      {/* 单元测试卡（自建算子） */}
      {isCustom && (
        <Card>
          <CardHeader><CardTitle>单元测试（对应环境容器执行真实算子代码）</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Field label="测试输入 JSON">
              <Textarea rows={4} className="font-mono text-xs" value={testInputs} onChange={(e) => setTestInputs(e.target.value)} />
            </Field>
            <div className="flex items-center gap-3">
              <Button variant="secondary" className="h-8 text-xs" disabled={testing} onClick={runUnitTest}>
                {testing ? "执行中…" : "运行单元测试"}
              </Button>
              {testResult && (
                <Badge tone={testResult.status === "passed" ? "success" : "destructive"}>
                  {testResult.status === "passed" ? "通过" : "失败"}
                </Badge>
              )}
              {testResult?.duration_ms !== undefined && (
                <span className="text-xs tabular-nums text-muted-foreground">{testResult.duration_ms}ms</span>
              )}
            </div>
            {testResult?.output !== undefined && testResult.output !== null && (
              <pre className="max-h-40 overflow-auto rounded-md border border-border bg-muted/30 p-2.5 font-mono text-[11px]">
                {JSON.stringify(testResult.output, null, 2)}
              </pre>
            )}
            {testResult?.error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2.5 font-mono text-xs text-destructive">
                {testResult.error}
              </div>
            )}
            <p className="text-xs text-muted-foreground">发布门禁：只有单元测试通过的版本才允许发布。</p>
          </CardContent>
        </Card>
      )}

      {/* 版本历史 */}
      <Card>
        <CardHeader><CardTitle>版本历史（每次修改自动赋予新版本号）</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {versionRows.map((v) => (
            <div key={v.version} className="flex items-center justify-between gap-2 rounded-md border border-border/70 px-3 py-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium font-mono">{v.version}</span>
                  {v.status === "PUBLISHED" && <Badge tone="success">PUBLISHED</Badge>}
                  {v.status === "SUPERSEDED" && <Badge>SUPERSEDED</Badge>}
                  {asset.current_version === v.version && <Badge tone="primary">当前</Badge>}
                  {v.unit_test === "passed" && <Badge tone="success">单测通过</Badge>}
                </div>
                <div className="truncate text-xs text-muted-foreground">{v.changelog || "—"} · {v.created_by}</div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* 被引用清单（跳转） */}
      <Card>
        <CardHeader><CardTitle>被引用（{referenced.length}）——点击跳转到对应资产</CardTitle></CardHeader>
        <CardContent>
          {referenced.length ? (
            <ul className="space-y-1.5 text-xs">
              {referenced.map((ref) => {
                const link = parseRef(ref);
                return link ? (
                  <li key={ref}>
                    <Link to={link.to} className="font-mono text-primary hover:underline">{ref}</Link>
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
    </div>
  );
}
