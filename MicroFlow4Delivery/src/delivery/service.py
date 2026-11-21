"""REST 面（FastAPI）：与 CLI 共享同一 DeliveryStore 判定源。

边界声明：产物登记（含大文件）走 CLI 本地通道；REST 面承载团队推进工作流
（读取 / 推进 / 审计）。信封 `{code, data, message, trace_id}` 与宿主契约同形。
"""
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .errors import DeliveryError, GateRejected
from .store import ENVS, DeliveryStore


class PromoteRequest(BaseModel):
    env: str = Field(pattern="|".join(ENVS))
    actor: str = Field(min_length=1)
    approver: str | None = None


def create_app(store: DeliveryStore) -> FastAPI:
    app = FastAPI(title="MicroFlow4Delivery", version="0.1.0")

    def envelope(data: dict, message: str = "ok") -> dict:
        return {"code": 0, "data": data, "message": message, "trace_id": uuid.uuid4().hex}

    @app.get("/api/v1/artifacts")
    def list_artifacts() -> dict:
        return envelope({"artifacts": store.list_artifacts()})

    @app.get("/api/v1/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict:
        artifact = store.get_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="unknown artifact")
        return envelope({"artifact": artifact})

    @app.get("/api/v1/pointers")
    def list_pointers() -> dict:
        return envelope({"pointers": store.pointers()})

    @app.get("/api/v1/audit")
    def list_audit(limit: int = 100) -> dict:
        return envelope({"events": store.audit(limit=limit)})

    @app.post("/api/v1/artifacts/{artifact_id}/promote")
    def promote(artifact_id: str, request: PromoteRequest) -> dict:
        try:
            pointer = store.promote(artifact_id, request.env,
                                    actor=request.actor, approver=request.approver)
        except GateRejected as exc:
            raise HTTPException(status_code=409,
                                detail={"code": "GATE_REJECTED", "gates": exc.reasons}) from exc
        except DeliveryError as exc:
            status = 404 if exc.code == "UNKNOWN_ARTIFACT" else 422
            raise HTTPException(status_code=status,
                                detail={"code": exc.code, "message": exc.message}) from exc
        return envelope({"pointer": pointer})

    return app
