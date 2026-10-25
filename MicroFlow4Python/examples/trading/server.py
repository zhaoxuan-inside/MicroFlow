"""交易平台宿主适配：标准库 HTTP 服务承载本地演练执行。

宿主职责（平台标准 §20/§27）：把框架执行能力包装为网络接口。本服务是
本地演练宿主——显式 ephemeral、纯计算/读取算子、无耐久与恢复保证；
生产耐久服务由宿主按 T14 控制面与持久化提供者协议另行实现。

接口（全部 JSON，UTF-8；调用成功 ≠ 业务成功，业务结果看 Output.meta.status）：
- GET  /health         → 存活、releaseId、可用流程
- POST /run/{flow_id}  → 请求体为流程输入，返回标准 Output（meta/data/error）
- GET  /ops/report     → 运行固定演练组，返回监控/运营聚合报告

启动：PYTHONPATH=../../src python3 server.py [port]   # 默认 8310
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from microflow import LocalRuntime, discover  # noqa: E402
from microflow.compiler import compile_release  # noqa: E402
from microflow.errors import MicroFlowError  # noqa: E402
from microflow.values import load_json, thaw  # noqa: E402

registry = discover([HERE / "trading_ops.py"])
flows = load_json((HERE / "trading.project.json").read_text(encoding="utf-8"))["flows"]
release = compile_release(registry, flows,
                          defaults={"durability": "ephemeral", "recovery": {"enabled": False}})
runtime = LocalRuntime(release)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "protocol": "microflow-local-host-v1",
                             "releaseId": release.release_id, "durability": "ephemeral",
                             "flows": sorted(release.flows)})
        elif self.path == "/ops/report":
            import ops_report
            self._send(200, ops_report.build_report())
        else:
            self._send(404, {"error_code": "NOT_FOUND", "path": self.path})

    def do_POST(self):
        if not self.path.startswith("/run/"):
            self._send(404, {"error_code": "NOT_FOUND", "path": self.path})
            return
        flow_id = self.path[len("/run/"):].strip("/")
        if flow_id not in release.flows:
            self._send(404, {"error_code": "UNKNOWN_FLOW", "flow": flow_id,
                             "flows": sorted(release.flows)})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = load_json(raw.decode("utf-8"))
            outcome = runtime.run(flow_id, data)
        except MicroFlowError as exc:
            self._send(400, {"error_code": exc.diagnostic.error_code,
                             "message": exc.diagnostic.message})
            return
        self._send(200, thaw(outcome.output))

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8310
    print(f"trading host (ephemeral local runtime) on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
