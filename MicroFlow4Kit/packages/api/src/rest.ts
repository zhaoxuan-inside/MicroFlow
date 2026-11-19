/** 控制面 REST 客户端（FastAPI 控制面 :8200，经各 SPA 的 /orch-api 代理）。
 *
 * 信封协议与 dispatch 一致：{code, data, message, trace_id}，200/201 为成功。
 * token 与编排平台共用（mf_orch_token）：同 origin 部署时三平台共享控制面会话，
 * 开发期分端口各自独立。401 统一清 token 并触发 onOrchUnauthorized 注册的回调，
 * 页面据此回落到控制面登录面——不各自散落处理。
 */
const ORCH_TOKEN_KEY = "mf_orch_token";
const ORCH_BASE = "/orch-api";

export class OrchRestError extends Error {
  constructor(public code: number, message: string, public traceId?: string) {
    super(message);
  }
}

export function getOrchToken(): string {
  return localStorage.getItem(ORCH_TOKEN_KEY) || "";
}
export function setOrchToken(token: string): void {
  localStorage.setItem(ORCH_TOKEN_KEY, token);
}
export function clearOrchToken(): void {
  localStorage.removeItem(ORCH_TOKEN_KEY);
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
export function onOrchUnauthorized(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export async function orchRest<T = unknown>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  payload?: Record<string, unknown>,
): Promise<T> {
  const token = getOrchToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  let res: Response;
  try {
    res = await fetch(ORCH_BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
      signal: controller.signal,
    });
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") {
      throw new OrchRestError(408, "控制面请求超时（15s）");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
  const body = await res.json();
  if (body.code !== 200 && body.code !== 201) {
    if (body.code === 401) {
      clearOrchToken();
      unauthorizedHandler?.();
    }
    throw new OrchRestError(body.code, body.message || "请求失败", body.trace_id);
  }
  return body.data as T;
}
