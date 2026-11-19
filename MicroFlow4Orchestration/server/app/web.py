"""Web 层共用件：统一信封、鉴权依赖、RBAC、异常包装。

安全基建（0.11.2 加固轮）：
- 会话 token 只以 sha256 摘要入库——库泄露不等于会话劫持；
- 登录失败按 IP+邮箱滑动窗口限流——暴力破解有成本；
- service token 常量时间比较——消除时序侧信道。
"""
import hashlib
import secrets
import time
import uuid
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse

from . import db


def hash_session_token(token: str) -> str:
    """会话令牌入库摘要：库内只存 sha256(token)。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# 登录失败限流：滑动窗口内 (ip, email) 失败超过阈值 → 拒绝直至窗口滑出。
_LOGIN_LIMIT = 10
_LOGIN_WINDOW_SECONDS = 300.0
_login_failures: dict[tuple[str, str], list[float]] = defaultdict(list)


def login_throttled(ip: str, email: str) -> bool:
    """返回 True 表示该 (ip, email) 已超限（只统计失败，成功登录清零）。"""
    key = (ip, email.lower())
    now = time.monotonic()
    window = [t for t in _login_failures[key] if now - t < _LOGIN_WINDOW_SECONDS]
    _login_failures[key] = window
    return len(window) >= _LOGIN_LIMIT


def record_login_failure(ip: str, email: str) -> None:
    key = (ip, email.lower())
    _login_failures[key].append(time.monotonic())


def clear_login_failures(ip: str, email: str) -> None:
    _login_failures.pop((ip, email.lower()), None)

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
        hash_session_token(token),
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
            # 500 对外只给通用面：内部异常细节（SQL/路径/堆栈语义）留服务端日志。
            import os
            print(f"[500] {type(exc).__name__}: {exc}")
            detail = exc if os.getenv("ORCH_DEBUG_ERRORS") == "1" else None
            return err(500, f"服务内部错误：{type(exc).__name__}" if detail is None
                       else f"{type(exc).__name__}: {exc}")
    return wrapper


SERVICE_TOKEN_DEFAULT = "orch-service-secret"


def require_service_token(request: Request) -> None:
    import os
    token = request.headers.get("X-Service-Token", "")
    expected = os.getenv("ORCH_SERVICE_TOKEN", SERVICE_TOKEN_DEFAULT)
    if expected == SERVICE_TOKEN_DEFAULT and not getattr(require_service_token, "_warned", False):
        print("[security] ORCH_SERVICE_TOKEN 仍为默认值——生产部署必须通过环境变量覆盖")
        require_service_token._warned = True  # type: ignore[attr-defined]
    if not secrets.compare_digest(token, expected):
        raise PermissionError("service token 无效")
