"""业务容器 HTTP 面：编排控制面下行通道（/container/*，X-Service-Token 校验）。

返回是普通 JSON（不是宿主信封）——控制面 lifecycle.py 直接读
``result["status"]`` / ``final_output`` / ``error_message``，与本面逐字对齐。
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def create_app(services) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    expected_token = os.getenv("MF_CONTAINER_SERVICE_TOKEN", "")

    def _authorized(request: Request) -> bool:
        if not expected_token:
            return False                       # 未配置令牌 = 全拒绝，不放行匿名
        return request.headers.get("x-service-token", "") == expected_token

    @app.post("/container/configs")
    async def configs(request: Request):
        if not _authorized(request):
            return _error(403, "missing or wrong X-Service-Token")
        try:
            return services.runtime.receive_config(await request.json())
        except (ValueError, LookupError) as error:
            return _error(422, str(error))

    @app.post("/container/debug")
    async def debug(request: Request):
        if not _authorized(request):
            return _error(403, "missing or wrong X-Service-Token")
        body = await request.json()
        try:
            return services.runtime.set_debug(bool(body.get("enabled")))
        except ValueError as error:
            return _error(422, str(error))

    @app.post("/container/execute/scenario")
    async def execute_scenario(request: Request):
        if not _authorized(request):
            return _error(403, "missing or wrong X-Service-Token")
        body = await request.json()
        code = str(body.get("scenario_code") or "").strip()
        if not code:
            return _error(422, "scenario_code is required")
        inputs = body.get("inputs") or {}
        if not isinstance(inputs, dict):
            return _error(422, "inputs must be an object")
        try:
            return await services.execute_scenario(code, inputs, version=body.get("version"))
        except LookupError as error:
            return _error(404, str(error))
        except Exception as error:  # noqa: BLE001 - 业务失败如实返回，不 500 假成功
            return JSONResponse(status_code=200,
                                 content={"status": "FAILED", "error_message": str(error)})

    @app.post("/container/operators/register")
    async def operators_register(request: Request):
        if not _authorized(request):
            return _error(403, "missing or wrong X-Service-Token")
        try:
            return services.runtime.register_operator(await request.json())
        except ValueError as error:
            return _error(422, str(error))

    @app.post("/container/operators/execute")
    async def operators_execute(request: Request):
        if not _authorized(request):
            return _error(403, "missing or wrong X-Service-Token")
        body = await request.json()
        name = str(body.get("name") or "").strip()
        if not name:
            return _error(422, "name is required")
        inputs = body.get("inputs") or {}
        if not isinstance(inputs, dict):
            return _error(422, "inputs must be an object")
        try:
            return await services.runtime.execute_operator(name, inputs)
        except LookupError as error:
            return _error(404, str(error))

    @app.get("/healthz")
    async def healthz():
        stats = services.stats()
        return {"ok": True, "env": services.runtime.env,
                "release_id": stats["release_id"], "flows": stats["flows"],
                "operators": stats["operators"], "debug": stats["debug"],
                "pump": {"ticks": stats["pump"]["ticks"], "acked": stats["pump"]["acked"]},
                "announced": stats["announced"]}

    return app
