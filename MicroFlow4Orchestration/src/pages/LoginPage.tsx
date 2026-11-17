import { useState } from "react";
import { useNavigate } from "react-router";
import { orchDispatch, setOrchToken } from "../orchClient";
import { Button, Card, CardContent, CardHeader, Input, Logo } from "@microflow4kit/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await orchDispatch<{ token: string }>(
        "POST", "/auth/login",
        { email, password },
      );
      setOrchToken(data.token);
      navigate("/overview");
    } catch (err: any) {
      setError(err.message || "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background p-4">
      {/* 品牌 Logo 固定在页面左上角（登录卡片只承载表单） */}
      <div className="absolute left-6 top-6">
        <Logo product="编排管理平台" />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <p className="text-xs text-muted-foreground">使用控制面账号登录（独立账号体系）</p>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={submit}>
            <Input
              type="email"
              placeholder="邮箱"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button className="w-full" disabled={busy}>
              {busy ? "登录中…" : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
