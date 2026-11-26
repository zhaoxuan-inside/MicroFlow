"""控制面上行客户端：容器 → 编排控制面（stdlib urllib，与 Registry push 同风格）。

两个通道（载荷与控制面 main.py 的接收端逐字对齐）：
- POST /api/container/register-operators  {env, operators:[{name, version, code, entry_function, …}]}
- POST /api/container/report-node-io      {env, records:[{scenario_code, version, env, node_id,
                                              inputs, outputs, status, duration_ms}]}
"""
import json
import urllib.error
import urllib.request


def _post_json(url: str, payload: dict, token: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-Service-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read() or b""
        raise ConnectionError(f"control plane rejected uplink: HTTP {error.code} "
                              f"{body[:200].decode('utf-8', 'replace')}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ConnectionError(f"cannot reach control plane: {error}") from error


class ControlPlaneClient:
    def __init__(self, base_url: str, token: str, env: str, *, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.env = env
        self.timeout = timeout

    def register_operators(self, operators: list) -> dict:
        """把本地算子目录上报给控制面（source=container:<env> 登记进目录）。"""
        return _post_json(f"{self.base_url}/api/container/register-operators",
                          {"env": self.env, "operators": operators}, self.token, self.timeout)

    def report_node_io(self, records: list) -> dict:
        """debug 模式逐算子上报：E2E 阶段门禁与告警求值的数据源。

        诚实边界：框架生命周期记录携带 status/durationMs，不携带逐算子的
        inputs/outputs 转储——这两列如实为 None，不伪造。
        """
        payload = {"env": self.env, "records": [{**record, "env": self.env}
                                                for record in records]}
        return _post_json(f"{self.base_url}/api/container/report-node-io",
                          payload, self.token, self.timeout)

    def announce_operators(self, catalog: dict) -> dict:
        """启动时自注册：{name: {code, entry_function, ref}} → 控制面目录。"""
        operators = [{"name": name, "version": entry["ref"].rsplit("@", 1)[-1],
                      "code": entry["code"], "entry_function": entry["entry_function"],
                      "display_name": name,
                      "description": entry["definition"].description}
                     for name, entry in catalog.items()]
        return self.register_operators(operators)
