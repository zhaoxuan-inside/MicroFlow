/** 资产复制入口：控制面目录内复制（保留最新版本内容，生成新编码）。 */
import { useState } from "react";
import { orchDispatch } from "../orchClient";
import { Button, Input } from "@microflow4kit/ui";


const ID_FIELD = { operator: "new_name", subgraph: "new_code", scenario: "new_code" } as const;

export function CopyToProject({
  assetKind,
  code,
  onCopied,
}: {
  assetKind: "operator" | "subgraph" | "scenario";
  code: string;
  onCopied?: (newCode: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (assetKind === "operator") {
    // 目录复制：仅目录层登记，业务容器在发布时接收算子代码
  }

  const copy = async () => {
    if (!newCode.trim()) return;
    setPending(true);
    setMessage(null);
    try {
      const route =
        assetKind === "operator"
          ? `/operators/${encodeURIComponent(code)}/copy`
          : assetKind === "subgraph"
            ? `/subgraphs/${encodeURIComponent(code)}/copy`
            : `/scenarios/${encodeURIComponent(code)}/copy`;
      const body = assetKind === "operator" ? { new_name: newCode.trim() } : { new_code: newCode.trim() };
      const result = await orchDispatch<{ name?: string; code?: string }>("POST", route, body);
      const landed = result.name || result.code || "";
      setMessage(landed ? `已复制为 ${landed}` : "复制成功");
      setNewCode("");
      setOpen(false);
      onCopied?.(landed);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <Button variant="secondary" className="h-7 text-xs" onClick={() => setOpen(!open)}>
        复制
      </Button>
      {open && (
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-background p-1.5">
          <Input
            aria-label="新编码"
            placeholder="新编码（可选）"
            className="h-7 w-40 text-xs"
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
          />
          <Button className="h-7 text-xs" disabled={pending || !newCode.trim()} onClick={copy}>
            {pending ? "复制中…" : "确认复制"}
          </Button>
        </div>
      )}
      {message && <div className="text-xs text-muted-foreground">{message}</div>}
    </div>
  );
}
