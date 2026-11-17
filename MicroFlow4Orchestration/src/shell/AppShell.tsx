import { NavLink, Outlet, useNavigate } from "react-router";
import { useScope } from "../orchAuth";
import { orchDispatch, getOrchToken, clearOrchToken } from "../orchClient";
import { Button, CommandPalette, useTheme, type CommandEntry } from "@microflow4kit/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const ENV_KEY = "mf_orch_env";

const NAV = [
  { to: "/overview", label: "总览", icon: "◎" },
  { to: "/operators", label: "算子", icon: "⚙" },
  { to: "/subgraphs", label: "子图", icon: "⛓" },
  { to: "/scenarios", label: "场景", icon: "⎇" },
  { to: "/releases", label: "版本与发布", icon: "⎋" },
  { to: "/experiments", label: "实验", icon: "⚗" },
  { to: "/configs", label: "配置管理", icon: "▤" },
];

/** 控制面环境选择器（业务容器按环境部署，策略下发目标）。 */
function EnvironmentSwitcher() {
  const envs = useQuery({
    queryKey: ["orch-envs"],
    queryFn: () => orchDispatch<{ envs: Array<{ env: string; base_url: string }> }>("GET", "/envs"),
  });
  const [current, setCurrent] = useState(localStorage.getItem(ENV_KEY) || "");
  const list = envs.data?.envs || [];
  useEffect(() => {
    if (!current && list.length) {
      setCurrent(list[0].env);
      localStorage.setItem(ENV_KEY, list[0].env);
    }
  }, [list, current]);
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground">环境</span>
      <select
        aria-label="选择发布环境"
        className="h-8 rounded-md border border-border bg-background px-2 text-xs"
        value={current}
        onChange={(e) => {
          setCurrent(e.target.value);
          localStorage.setItem(ENV_KEY, e.target.value);
        }}
      >
        {list.map((e) => (
          <option key={e.env} value={e.env}>{e.env}</option>
        ))}
      </select>
    </div>
  );
}

export function currentEnv(): string {
  return localStorage.getItem(ENV_KEY) || "dev";
}

export function AppShell() {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const { user, myScope, loading } = useScope();

  useEffect(() => {
    if (!getOrchToken()) navigate("/login");
  }, [navigate]);

  useEffect(() => {
    if (!loading && !user) navigate("/login");
  }, [loading, user, navigate]);

  const entries: CommandEntry[] = [
    ...NAV.map((item) => ({ id: item.to, label: item.label, group: "导航", icon: item.icon, onSelect: () => navigate(item.to) })),
    { id: "action-theme", label: theme === "dark" ? "切换到亮色主题" : "切换到暗色主题", group: "操作", icon: "☾", onSelect: toggle },
    { id: "action-logout", label: "退出登录", group: "操作", icon: "⎋", onSelect: () => { clearOrchToken(); navigate("/login"); } },
  ];

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2 border-b border-border px-5">
          <span className="text-sm font-semibold tracking-tight">MicroFlow 编排管理</span>
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
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-3 border-b border-border bg-card px-5">
          <EnvironmentSwitcher />
          <Button variant="ghost" aria-label="命令面板" className="h-8 gap-1.5 px-2 font-mono text-[11px] text-muted-foreground" onClick={() => dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }))}>
            ⌘K
          </Button>
          <Button variant="ghost" onClick={toggle} aria-label="切换主题">
            {theme === "dark" ? "☀" : "☾"}
          </Button>
          <span className="text-sm text-muted-foreground">
            {user?.nickname || user?.email || myScope.user_id || "…"}
          </span>
          <Button
            variant="secondary"
            onClick={() => {
              // 登出为客户端行为：清除控制面会话令牌即失效
              clearOrchToken();
              navigate("/login");
            }}
          >
            退出
          </Button>
        </header>
        <main className="min-w-0 flex-1 space-y-4 p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette entries={entries} />
    </div>
  );
}
