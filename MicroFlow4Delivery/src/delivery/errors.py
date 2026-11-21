"""交付域异常：门禁否定与请求失败分层（对应 CLI 退出码 1/2）。"""
from typing import Any


class DeliveryError(Exception):
    """请求无法完成（exit 2）：文件不可用、证据信封损坏、未知引用。"""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def envelope(self) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {"error_code": self.code, "message": self.message}
        if self.detail:
            diagnostic["detail"] = self.detail
        return {"protocol": "microflow-delivery-v1", "ok": False, "diagnostic": diagnostic}


class GateRejected(Exception):
    """发布门禁否定（exit 1）：携带逐门禁拒绝原因列表。"""

    def __init__(self, reasons: list[dict[str, str]]):
        super().__init__("; ".join(r["reason"] for r in reasons))
        self.reasons = reasons

    def envelope(self) -> dict[str, Any]:
        return {"protocol": "microflow-delivery-v1", "ok": False, "gates": self.reasons}
