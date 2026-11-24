"""MicroFlow 支持平台静态服务 + 反向代理（部署管道，非业务代码）。

一个进程按环境变量服务一个支持平台 SPA 的 dist 构建产物：

- ``SUPPORT_APP``  = orchestration | ops | bizops（决定启用哪些代理）
- ``SUPPORT_PORT`` = 监听端口（约定 orchestration=4601 / ops=4602 / bizops=4603）
- ``SUPPORT_DIST`` = 该 SPA 的 dist 目录（compose 挂载为只读）

代理规则（与各子项目 vite dev 代理完全对齐，SPA 源码零改动）：

- ``/api/*``       → OpcHub 业务后端网关（backend:8000，原样转发，Kit 默认端点
  ``/api/v1/dispatch`` 已被网关声明为别名）
- ``/orch-api/*``  → MicroFlow4Orchestration 独立控制面（orch-control:8200），
  改写前缀 ``/orch-api`` → ``/api``（控制面路由统一挂在 /api 下）

静态面：``/assets/*`` 哈希产物 immutable 长缓存；其余路径 SPA fallback 到
index.html（no-cache）；GZip + 基础安全头。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("support-platform")

SUPPORT_APP = os.getenv("SUPPORT_APP", "ops").strip().lower()
SUPPORT_PORT = int(os.getenv("SUPPORT_PORT", "4602"))
DIST_DIR = Path(os.getenv("SUPPORT_DIST", "/srv/dist")).resolve()
BACKEND_URL = os.getenv("OPCHUB_BACKEND_URL", "http://backend:8000").rstrip("/")
ORCH_CONTROL_URL = os.getenv("ORCH_CONTROL_URL", "http://orch-control:8200").rstrip("/")
# orchestration 与 ops 的告警中心都消费控制面；bizops 仅走业务后端网关。
ORCH_PROXY_ENABLED = os.getenv("SUPPORT_ORCH_PROXY", "1" if SUPPORT_APP in ("orchestration", "ops") else "0") == "1"

if not (DIST_DIR / "index.html").is_file():
    raise SystemExit(f"[support-platform] dist index.html 不存在: {DIST_DIR}/index.html（先构建对应 SPA）")

app = FastAPI(docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# -----------------------------------------------------------------------------
# Reverse proxies（hop-by-hop 头过滤；流式转发不缓冲请求体）
# -----------------------------------------------------------------------------
_HOP_BY_HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "accept-encoding"}
_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))


def _forward_headers(headers):
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


async def _proxy(request: Request, target_base: str, target_path: str) -> StreamingResponse:
    url = target_base + target_path
    if request.url.query:
        url += "?" + request.url.query
    body = await request.body()
    try:
        upstream = await _client.request(
            request.method,
            url,
            headers=_forward_headers(request.headers),
            content=body if body else None,
        )
    except httpx.RequestError as exc:
        logger.warning("proxy %s %s -> %s: %s", request.method, request.url.path, url, exc)
        return JSONResponse({"error": "upstream_unavailable", "detail": str(exc)}, status_code=502)
    headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
    }
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=headers,
        background=None,
    )


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_backend(request: Request, rest: str):
    """业务后端网关（/api/v1/dispatch 为 /api/welcom/opc_world 的网关别名）。"""
    return await _proxy(request, BACKEND_URL, "/api/" + rest)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "app": SUPPORT_APP, "dist": str(DIST_DIR)}


if ORCH_PROXY_ENABLED:
    @app.api_route("/orch-api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy_orch_control(request: Request, rest: str):
        """编排独立控制面（控制面路由统一挂 /api 前缀，SPA 侧 BASE=/orch-api）。"""
        return await _proxy(request, ORCH_CONTROL_URL, "/api/" + rest)


# -----------------------------------------------------------------------------
# 静态面：哈希资产 immutable；其余 SPA fallback 到 index.html（no-cache）
# -----------------------------------------------------------------------------
_ASSETS = DIST_DIR / "assets"

# 首帧错误采集器（诊断用，注入在所有模块脚本之前执行；SUPPORT_INJECT_DIAG=0 关闭）
_INJECT_DIAGNOSTICS = os.getenv("SUPPORT_INJECT_DIAG", "1") == "1"
_DIAG_SCRIPT = (
    "<script>window.__errs=[];"
    "window.addEventListener('error',function(e){var m='ERR: '+(e.message||'');"
    "if(e.target&&e.target.tagName)m+=' RES:'+(e.target.src||e.target.href||'').split('/').pop();"
    "if(e.error&&e.error.stack)m+=' | '+String(e.error.stack).slice(0,400);"
    "window.__errs.push(m);},true);"
    "window.addEventListener('unhandledrejection',function(e){"
    "window.__errs.push('REJ: '+String(e.reason).slice(0,400));});</script>"
)


def _serve_index() -> "Response":
    """SPA fallback：no-cache 直出 index.html（可选注入首帧诊断采集器）。"""
    index = DIST_DIR / "index.html"
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    if not _INJECT_DIAGNOSTICS:
        return FileResponse(index, headers=headers)
    try:
        html = index.read_text(encoding="utf-8")
        if "__errs" not in html:
            html = html.replace("<head>", "<head>" + _DIAG_SCRIPT, 1)
        return Response(content=html, media_type="text/html", headers=headers)
    except Exception:
        return FileResponse(index, headers=headers)


@app.get("/assets/{rest:path}")
async def hashed_assets(rest: str):
    file = (_ASSETS / rest).resolve()
    if not file.is_file() or _ASSETS.resolve() not in file.parents:
        return JSONResponse({"error": "asset_not_found"}, status_code=404)
    return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/{rest:path}")
async def spa_fallback(rest: str):
    candidate = (DIST_DIR / rest).resolve()
    if rest and candidate.is_file() and DIST_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    return _serve_index()


if __name__ == "__main__":
    logger.info(
        "support-platform[%s] dist=%s port=%d backend=%s orch_proxy=%s",
        SUPPORT_APP, DIST_DIR, SUPPORT_PORT, BACKEND_URL, ORCH_PROXY_ENABLED,
    )
    uvicorn.run(app, host="0.0.0.0", port=SUPPORT_PORT, log_level="info", access_log=False)
