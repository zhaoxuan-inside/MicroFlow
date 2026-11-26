"""宿主 dispatch 桩（与 Registry 测试同协议 {code,data,message,trace_id}；仅测试用）。"""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        self.server.requests.append({"body": body,
                                     "token": self.headers.get("X-Service-Token", ""),
                                     "authorization": self.headers.get("Authorization", "")})
        status, payload = self.server.responder(self.server)
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        return


@contextmanager
def dispatch_stub(responder=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.responder = responder or (
        lambda _srv: (200, {"code": 0, "data": {"status": "registered"},
                            "message": "ok", "trace_id": "trace-1"}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        server.endpoint = f"http://{host}:{port}/api/v1/dispatch"
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
