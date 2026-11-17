/** 编排管理平台控制面客户端（:8200 独立后端）——信封协议与 kit client 一致。 */
const TOKEN_KEY = "mf_orch_token";
const BASE = "/orch-api";

export class OrchError extends Error {
  constructor(public code: number, message: string, public traceId?: string) {
    super(message);
  }
}

export function getOrchToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setOrchToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearOrchToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function orchDispatch<T = any>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  payload?: Record<string, unknown>,
): Promise<T> {
  const token = getOrchToken();
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
  });
  const body = await res.json();
  if (body.code !== 200 && body.code !== 201) {
    // 会话失效统一兜底：清 token 回登录页（各页面无需各自处理 401）。
    if (body.code === 401) {
      clearOrchToken();
      if (!location.pathname.startsWith("/login")) {
        location.assign("/login");
      }
    }
    throw new OrchError(body.code, body.message || "请求失败", body.trace_id);
  }
  return body.data as T;
}
