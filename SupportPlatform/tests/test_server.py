"""Deployment-shell acceptance: traversal refusal, cache semantics, proxy rewrite, 502.

The shell has no business semantics, but it owns the risk surface that is
easiest to get wrong (path handling, caching, prefix rewrites, upstream
failure). These four behaviors are asserted against the real app object.
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
from unittest import mock

DIST = Path(tempfile.mkdtemp(prefix="support-platform-dist-"))
(DIST / "assets").mkdir()
(DIST / "index.html").write_text(
    "<html><head></head><body>SPA-SHELL</body></html>", encoding="utf-8")
(DIST / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
SECRET = DIST.parent / "support-platform-secret.txt"
SECRET.write_text("TOP_SECRET_MUST_NOT_LEAK", encoding="utf-8")

os.environ.update({
    "SUPPORT_APP": "ops",
    "SUPPORT_PORT": "4602",
    "SUPPORT_DIST": str(DIST),
    "SUPPORT_ORCH_PROXY": "1",
    "SUPPORT_INJECT_DIAG": "0",
    "OPCHUB_BACKEND_URL": "http://backend:8000",
    "ORCH_CONTROL_URL": "http://orch-control:8200",
})

SOURCE = Path(__file__).resolve().parent.parent / "server.py"
_SPEC = importlib.util.spec_from_file_location("support_platform_server", SOURCE)
server = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = server
_SPEC.loader.exec_module(server)

from starlette.testclient import TestClient  # noqa: E402 - app must exist first


class _Upstream:
    def __init__(self, status=200, body=b'{"ok":true}', headers=None):
        self.status_code = status
        self.headers = headers or {"content-type": "application/json"}
        self._body = body

    async def aiter_bytes(self):
        yield self._body


class _Client:
    """Stands in for the module-level httpx.AsyncClient."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def request(self, method, url, headers=None, content=None):
        self.calls.append({"method": method, "url": url})
        if self.error is not None:
            raise self.error
        return self.result


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, raise_server_exceptions=True)

    def test_healthz_names_the_app_and_dist(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app"], "ops")

    def test_orch_proxy_rewrites_prefix_and_keeps_query(self):
        fake = _Client(_Upstream())
        with mock.patch.object(server, "_client", fake):
            response = self.client.get("/orch-api/experiments?limit=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.calls[0]["url"], "http://orch-control:8200/api/experiments?limit=5")

    def test_business_backend_proxy_keeps_its_prefix(self):
        fake = _Client(_Upstream())
        with mock.patch.object(server, "_client", fake):
            response = self.client.post("/api/v1/dispatch", json={"scenario": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.calls[0]["url"], "http://backend:8000/api/v1/dispatch")
        self.assertEqual(fake.calls[0]["method"], "POST")

    def test_upstream_unavailable_is_an_honest_502(self):
        fake = _Client(error=httpx.ConnectError("connection refused"))
        with mock.patch.object(server, "_client", fake):
            response = self.client.get("/api/v1/dispatch")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "upstream_unavailable")

    def test_hashed_assets_are_immutable(self):
        response = self.client.get("/assets/app-abc123.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response.headers["cache-control"])
        self.assertIn("max-age=31536000", response.headers["cache-control"])

    def test_asset_traversal_is_refused(self):
        # Direct call bypasses any client-side URL normalization: this is the
        # exact string a raw HTTP client could deliver to the route.
        direct = asyncio.run(server.hashed_assets("../support-platform-secret.txt"))
        self.assertEqual(direct.status_code, 404)

        for attempt in ("/assets/..%2Fsupport-platform-secret.txt",
                        "/assets/../support-platform-secret.txt"):
            response = self.client.get(attempt)
            self.assertNotIn("TOP_SECRET_MUST_NOT_LEAK", response.text, attempt)
            if response.status_code == 200:
                self.assertIn("SPA-SHELL", response.text, attempt)  # normalized to fallback
            else:
                self.assertEqual(response.status_code, 404, attempt)

    def test_spa_fallback_never_leaks_files_outside_dist(self):
        response = self.client.get("/..%2Fsupport-platform-secret.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SPA-SHELL", response.text)
        self.assertNotIn("TOP_SECRET_MUST_NOT_LEAK", response.text)
        self.assertIn("no-cache", response.headers["cache-control"])

    def test_spa_fallback_serves_existing_files(self):
        (DIST / "robots.txt").write_text("User-agent: *", encoding="utf-8")
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("User-agent", response.text)


if __name__ == "__main__":
    unittest.main()
