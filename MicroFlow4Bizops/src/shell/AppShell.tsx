import { NavLink, Outlet, useNavigate } from "react-router";
import { clearScope, clearToken, getToken, dispatch } from "@microflow4kit/api";
import { Button, CommandPalette, LocaleSwitcher, PermissionGate, ScopeEmptyHint, ScopeSwitcher, useTheme, useScope, type CommandEntry } from "@microflow4kit/ui";
import { Logo } from "@microflow4kit/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";

const NAV = [
  { to: "/overview", labelKey: "nav.overview", icon: "◎" },
  { to: "/funnel", labelKey: "nav.funnel", icon: "⏳" },
  { to: "/retention", labelKey: "nav.retention", icon: "▦" },
  { to: "/experiments", labelKey: "nav.experiments", icon: "⚗" },
];

const PLATFORM_NAV = [
  { to: "/platform/tenants", labelKey: "ui:common.tenant", icon: "🗄", anyOf: ["platform:tenant_manage", "tenant:member_manage", "tenant:project_create"] },
  { to: "/platform/projects", labelKey: "ui:common.project", icon: "🗂", anyOf: ["tenant:project_create", "project:member_manage", "tenant:member_manage"] },
  { to: "/platform/roles", labelKey: "admin:roles.title", icon: "🔏", anyOf: ["platform:role_manage", "tenant:role_manage"] },
  { to: "/platform/users", labelKey: "ui:common.user", icon: "👥", anyOf: ["platform:user_manage"] },
];

export function AppShell() {
  const { t } = useTranslation("bizops");
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const { myScope } = useScope();

  useEffect(() => {
    if (!getToken()) navigate("/login");
  }, [navigate]);

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => dispatch("auth.session", {}),
    retry: false,
  });

  useEffect(() => {
    if (session.isError) {
      clearToken();
      navigate("/login");
    }
  }, [session.isError, navigate]);

  const entries: CommandEntry[] = [
    ...NAV.map((item) => ({ id: item.to, label: t(item.labelKey), group: t("ui:palette.groupNav"), icon: item.icon, onSelect: () => navigate(item.to) })),
    ...PLATFORM_NAV.map((item) => ({ id: item.to, label: t(item.labelKey), group: t("shell.platformSection"), icon: item.icon, onSelect: () => navigate(item.to) })),
    { id: "action-theme", label: theme === "dark" ? t("ui:palette.toLight") : t("ui:palette.toDark"), group: t("ui:palette.groupActions"), icon: "☾", onSelect: toggle },
    { id: "action-locale", label: i18next.language === "zh" ? t("ui:palette.toEnglish") : t("ui:palette.toChinese"), group: t("ui:palette.groupActions"), icon: "文", onSelect: () => void i18next.changeLanguage(i18next.language === "zh" ? "en" : "zh") },
    { id: "action-logout", label: t("shell.logout"), group: t("ui:palette.groupActions"), icon: "⎋", onSelect: () => { clearToken(); clearScope(); navigate("/login"); } },
  ];

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2 border-b border-border px-5">
          <Logo product={t("shell.product")} />
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                ].join(" ")
              }
            >
              <span aria-hidden className="w-4 text-center opacity-80">{item.icon}</span>
              {t(item.labelKey)}
            </NavLink>
          ))}
          <div className="mt-4 flex items-center gap-2 px-3 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
            {t("shell.platformSection")}
          </div>
          {PLATFORM_NAV.map((item) => (
            <PermissionGate key={item.to} anyOf={item.anyOf}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  ].join(" ")
                }
              >
                <span aria-hidden className="w-4 text-center opacity-80">{item.icon}</span>
                {t(item.labelKey)}
              </NavLink>
            </PermissionGate>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-3 border-b border-border bg-card px-5">
          <ScopeSwitcher />
          <LocaleSwitcher />
          <Button variant="ghost" aria-label="命令面板" className="h-8 gap-1.5 px-2 font-mono text-[11px] text-muted-foreground" onClick={() => dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }))}>
            ⌘K
          </Button>
          <Button variant="ghost" onClick={toggle} aria-label={t("shell.themeAria")}>
            {theme === "dark" ? "☀" : "☾"}
          </Button>
          <span className="text-sm text-muted-foreground">
            {(session.data as any)?.nickname || (session.data as any)?.email || myScope?.user_id || "…"}
          </span>
          <Button
            variant="secondary"
            onClick={() => {
              // 登出为客户端行为：会话令牌无服务端存储，清除本地令牌即失效（宿主契约）；
              // 活动租户/项目 scope 一并清除，避免换号登录残留上一账号的选择
              clearToken();
              clearScope();
              navigate("/login");
            }}
          >
            {t("shell.logout")}
          </Button>
        </header>
        <main className="min-w-0 flex-1 space-y-4 p-6">
          <ScopeEmptyHint hint={t("shell.emptyHint")} />
          <Outlet />
        </main>
      </div>
      <CommandPalette entries={entries} />
    </div>
  );
}
