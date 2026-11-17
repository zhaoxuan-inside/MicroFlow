/** 控制面账号体系垫片：与 Kit useScope 同形状，数据源为控制面 /auth/me。 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { orchDispatch, getOrchToken, clearOrchToken } from "./orchClient";

interface OrchUser {
  user_id: string;
  email: string;
  nickname: string;
  role: string;
  permissions: string[];
}

const emptyScope = {
  user_id: "",
  is_platform_super: false,
  tenants: [] as unknown[],
  projects: [] as unknown[],
  activeEnvironments: [] as Array<{ key: string; name: string; protected: boolean }>,
};

const OrchAuthContext = createContext<{
  user: OrchUser | null;
  loading: boolean;
  hasPermission: (perm: string) => boolean;
  activeEnvironments: Array<{ key: string; name: string; protected: boolean }>;
  myScope: typeof emptyScope;
  refresh: () => void;
}>({
  user: null,
  loading: false,
  hasPermission: () => false,
  activeEnvironments: [],
  myScope: emptyScope,
  refresh: () => {},
});

export function OrchAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<OrchUser | null>(null);
  // 已持 token 时初始即处于"会话确认中"，避免 AppShell 在 /auth/me 返回前
  // 误判未登录而立刻踢回登录页（首次渲染竞态）。
  const [loading, setLoading] = useState(() => Boolean(getOrchToken()));
  const [tick, setTick] = useState(0);
  const [envs, setEnvs] = useState<Array<{ key: string; name: string; protected: boolean }>>([]);

  useEffect(() => {
    if (!getOrchToken()) {
      setUser(null);
      return;
    }
    setLoading(true);
    orchDispatch<OrchUser>("GET", "/auth/me")
      .then(setUser)
      .catch(() => {
        clearOrchToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
    orchDispatch<{ envs: Array<{ env: string }> }>("GET", "/envs")
      .then((d) => setEnvs((d.envs || []).map((e) => ({
        key: e.env, name: e.env, protected: e.env === "staging" || e.env === "online",
      }))))
      .catch(() => setEnvs([]));
  }, [tick]);

  const perms = new Set(user?.permissions || []);
  const isSuper = user?.role === "admin";
  const value = {
    user,
    loading,
    refresh: () => setTick((t) => t + 1),
    hasPermission: (perm: string) => isSuper || perms.has(perm),
    activeEnvironments: envs,
    myScope: {
      ...emptyScope,
      user_id: user?.user_id || "",
      is_platform_super: isSuper,
    },
  };
  return <OrchAuthContext.Provider value={value}>{children}</OrchAuthContext.Provider>;
}

/** 与 Kit useScope 同形状：页面无需改动即可切换到控制面账号体系。 */
export function useScope() {
  return useContext(OrchAuthContext);
}

/** 与 Kit PermissionGate 同形（{permission?, anyOf?, children, fallback}）：
 * 数据源为控制面账号（orchAuth），避免强耦合 Kit ScopeProvider。 */
export function PermissionGate({
  permission,
  anyOf,
  children,
  fallback = null,
}: {
  permission?: string;
  anyOf?: string[];
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { hasPermission, loading } = useScope();
  if (loading) return null;
  const granted = permission ? hasPermission(permission) : false;
  const grantedAny = (anyOf || []).some((p) => hasPermission(p));
  return <>{granted || grantedAny ? children : fallback}</>;
}
