"""装配：内核协调器 + 记录流 + 投递泵 + 控制面上行，一次接成。

这是"整套"最后几根线的接法图：内核暴露 pending/acknowledge 读面与
record_sink 端口，本模块只做接线——传输归 MicroFlow4Registry，上行归
ControlPlaneClient，内核始终不知道它们的名字。
"""
import hashlib
import json

from microflow_registry import EventPump, RecordStream
from microflow_registry.push import resolve_config
from microflow_registry.store import Store

from .control import ControlPlaneClient
from .runtime import ContainerRuntime


def stable_request_id(intent) -> str:
    """泵重试的幂等键：同一意图的确认永远同一 request_id。"""
    body = json.dumps({"ack": intent["event_id"], "content_digest": intent["content_digest"]},
                      sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def records_to_node_io(records: list, *, scenario_code: str, version: str) -> list:
    """生命周期记录 → 控制面 debug_io 行（inputs/outputs 如实为 None）。"""
    rows = []
    for record in records:
        if record.get("event") != "attempt_finished":
            continue
        rows.append({"scenario_code": scenario_code, "version": version,
                     "node_id": str(record.get("operatorName") or ""),
                     "inputs": None, "outputs": None,
                     "status": str(record.get("status") or ""),
                     "duration_ms": float(record.get("durationMs") or 0)})
    return rows


class ContainerServices:
    def __init__(self, *, runtime: ContainerRuntime, stream: RecordStream,
                 pump: EventPump, control: ControlPlaneClient):
        self.runtime = runtime
        self.stream = stream
        self.pump = pump
        self.control = control
        self.announced = {"ok": False, "error": "not attempted"}

    def start(self) -> "ContainerServices":
        """启动后台投递 + 启动自注册（上行失败如实计数，不阻塞启动）。"""
        self.stream.start()
        self.pump.start()
        try:
            self.announced = {"ok": True,
                              "result": self.control.announce_operators(self.runtime.operator_catalog)}
        except Exception as error:  # noqa: BLE001 - 上行失败不阻塞容器启动
            self.announced = {"ok": False, "error": str(error)}
        return self

    def stop(self) -> None:
        self.pump.close()
        self.stream.close()

    async def execute_scenario(self, scenario_code: str, inputs: dict,
                               *, version: str | None = None) -> dict:
        result = await self.runtime.execute_scenario(scenario_code, inputs, version=version)
        if self.runtime.debug_enabled:
            rows = records_to_node_io(result["records"], scenario_code=scenario_code,
                                      version=result["version"])
            if rows:
                try:
                    self.uplink = self.control.report_node_io(rows)
                except Exception as error:  # noqa: BLE001 - 观测上行失败不影响业务结果
                    self.uplink = {"error": str(error)}
        return result

    def stats(self) -> dict:
        return {"release_id": self.runtime.release_id,
                "flows": sorted(self.runtime.flow_ids),
                "operators": sorted(self.runtime.operator_catalog),
                "configs": sorted(self.runtime.configs),
                "debug": self.runtime.debug_enabled,
                "pump": self.pump.stats(),
                "stream": self.stream.stats(),
                "announced": self.announced}


def build_services(*, project_path, store_dir, env, binding_id,
                   host_endpoint, host_token, control_url, control_token,
                   namespace, group, registry_store_dir=None,
                   execution_timeout=25.0,
                   pump_interval=5.0, stream_interval=5.0) -> ContainerServices:
    """按依赖序装配整套容器；registry_store_dir 缺省与状态库同目录。"""
    from pathlib import Path
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    stream = RecordStream(namespace=namespace, group=group,
                          config=resolve_config(endpoint=host_endpoint, token=host_token),
                          store=Store(registry_store_dir or (store_dir / "registry-outbox")),
                          capacity=1000, flush_size=100, flush_interval=stream_interval)
    runtime = ContainerRuntime(project_path=project_path,
                               store_path=store_dir / f"state-{env}.sqlite3",
                               env=env, binding_id=binding_id,
                               record_sink=stream.accept,
                               execution_timeout=execution_timeout)

    def acknowledge(intent):
        runtime.coordinator.acknowledge_event(intent["event_id"], intent["content_digest"],
                                              request_id=stable_request_id(intent))

    pump = EventPump(pending=runtime.coordinator.pending_events, acknowledge=acknowledge,
                     stream=stream, limit=100, interval=pump_interval)
    control = ControlPlaneClient(control_url, control_token, env)
    return ContainerServices(runtime=runtime, stream=stream, pump=pump, control=control)
