import { useState } from "react";
import { useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import { dispatch, setToken } from "@microflow4kit/api";
import { Button, Card, CardContent, CardHeader, Input } from "@microflow4kit/ui";
import { Logo } from "@microflow4kit/ui";

export function LoginPage() {
  const { t } = useTranslation("bizops");
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
      const data = await dispatch<{ token: string }>(
        "auth.login",
        { email, password },
      );
      setToken(data.token);
      navigate("/overview");
    } catch (err: any) {
      setError(err.message || t("login.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background p-4">
      {/* 品牌 Logo 固定在页面左上角（登录卡片只承载表单） */}
      <div className="absolute left-6 top-6">
        <Logo product={t("shell.product")} />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <p className="text-xs text-muted-foreground">{t("login.subtitle")}</p>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={submit}>
            <Input
              type="email"
              placeholder={t("login.email")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder={t("login.password")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button className="w-full" disabled={busy}>
              {busy ? t("login.submitting") : t("login.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
