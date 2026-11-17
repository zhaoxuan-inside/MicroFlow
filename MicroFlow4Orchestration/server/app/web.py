"""Web 层共用件：统一信封、鉴权依赖、RBAC、异常包装。"""
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from . import db

ROLE_PERMS = {
    "admin": {"orchestration:read", "orchestration:write", "page:orchestrate",
              "experiment:read", "experiment:manage",
              "configcenter:read", "configcenter:write", "ops:alerts"},
    "editor": {"orchestration:read", "orchestration:write", "page:orchestrate",
               "experiment:read", "experiment:manage",
               "configcenter:read", "configcenter:write", "ops:alerts"},
    "viewer": {"orchestration:read", "experiment:read", "configcenter:read"},
}


def envelope(data=None, code: int = 200, message: str = "success") -> JSONResponse:
    # JSONResponse 内部是裸 json.dumps，不经过 jsonable_encoder；
    # asyncpg 返回的 UUID/TIMESTAMPTZ 等必须在此统一编码为 JSON 原生类型。
    from fastapi.encoders import jsonable_encoder
    return JSONResponse({"code": code, "data": jsonable_encoder(data), "message": message,
                         "trace_id": uuid.uuid4().hex})


def err(code: int, message: str) -> JSONResponse:
    return envelope(None, code, message)


async def current_user(request: Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else request.headers.get("X-Orch-Token", "")
    if not token:
        return None
    pool = await db.pool()
    row = await pool.fetchrow(
        "SELECT user_id, email, nickname, role FROM sessions "
        "WHERE token = $1 AND expires_at > now()",
        token,
    )
    return dict(row) if row else None


async def require(request: Request, perm: str) -> dict:
    user = await current_user(request)
    if user is None:
        raise PermissionError("该操作需要登录")
    if perm not in ROLE_PERMS.get(user["role"], set()):
        raise PermissionError(f"权限不足：需要 {perm}")
    return user


def guard(fn):
    """统一信封包装：PermissionError→401/403，ValueError→400，KeyError→404，其余 500。"""
    async def wrapper(request: Request):
        try:
            data = await fn(request)
            return envelope(data)
        except PermissionError as exc:
            msg = str(exc)
            return err(401 if "需要登录" in msg else 403, msg)
        except ValueError as exc:
            return err(400, str(exc))
        except KeyError as exc:
            return err(404, exc.args[0] if exc.args else "对象不存在")
        except Exception as exc:  # noqa: BLE001
            return err(500, f"{type(exc).__name__}: {exc}")
    return wrapper


def require_service_token(request: Request) -> None:
    token = request.headers.get("X-Service-Token", "")
    import os
    if token != os.getenv("ORCH_SERVICE_TOKEN", "orch-service-secret"):
        raise PermissionError("service token 无效")
