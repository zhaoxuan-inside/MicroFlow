"""业务容器运行时：装载本地项目 + 接收控制面下发 + 耐久执行。

约定（与编排控制面逐字对齐，见 MicroFlow4Orchestration/server/app/lifecycle.py）：
- 下发的 graph 是**控制骨架**（canvas 协议，节点禁止携带 inputs）——可执行定义
  住在容器本地项目里，约定 ``flow.id == scenario_code``；
- 真耐久执行要求项目声明它绑定的介质：容器用自己的 binding_id 覆盖
  ``defaults.persistence_binding``（BINDING_MISMATCH 语义的正面用法）；
- 算子注册沿内核契约：推送的代码必须定义 ``register(registry)`` 声明 schema
  （scaffold 生成的就是这个形状）；仅 entry_function 的代码如实拒绝。
"""
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from microflow import ScheduledRuntime, create_provider, discover
from microflow.compiler import compile_release
from microflow.coordinator import Coordinator
from microflow.errors import ContractError, MicroFlowError
from microflow.runtime import LocalRuntime
from microflow.scheduling import ExecutionCommands
from microflow.values import digest, load_json, thaw

_PUSHED_DIR = "pushed"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def config_content_hash(value) -> str:
    """规范化 JSON 的 SHA-256——与控制面 lifecycle.config_content_hash 同语义。"""
    def tree(item):
        if isinstance(item, dict):
            return {key: tree(item[key]) for key in sorted(item)}
        if isinstance(item, list):
            return [tree(entry) for entry in item]
        return item
    canonical = json.dumps(tree(value), sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canvas_shaped(graph) -> bool:
    return isinstance(graph, dict) and "entry_node" in graph and "nodes" in graph


class ContainerRuntime:
    def __init__(self, *, project_path, store_path, env, binding_id,
                 record_sink=None, execution_timeout=25.0):
        self.project_path = Path(project_path)
        self.store_path = Path(store_path)
        self.env = env
        self.binding_id = binding_id
        self.record_sink = record_sink
        self.execution_timeout = execution_timeout
        self.debug_enabled = False
        self.configs: dict[str, dict] = {}
        self.release_id = ""
        self.flow_ids: set[str] = set()
        self.operator_catalog: dict[str, dict] = {}
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ---- 装载 ---------------------------------------------------------------

    def _load(self):
        config = load_json(self.project_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or set(config) - {"modules", "flows", "defaults"}:
            raise ContractError("INVALID_PROJECT", "Expected modules, flows and optional defaults")
        base = self.project_path.parent
        pushed = sorted((base / _PUSHED_DIR).glob("*.py")) if (base / _PUSHED_DIR).is_dir() else []
        modules = [base / name for name in config.get("modules", [])]
        registry = discover(modules + pushed)
        # 介质绑定是容器的事实：以自己的 binding_id 覆盖项目声明。
        defaults = {**(config.get("defaults") or {}), "persistence_binding": self.binding_id}
        provider = create_provider("sqlite", {"path": str(self.store_path),
                                              "binding_id": self.binding_id,
                                              "namespace": f"container-{self.env}"})
        coordinator = Coordinator(provider.state, durable=True)
        release = compile_release(registry, config["flows"], defaults=defaults,
                                  provider_capabilities=provider.describe().capabilities,
                                  source_file=str(self.project_path))
        self.commands = ExecutionCommands(coordinator, release, binding=provider.binding)
        self.provider = provider
        self.coordinator = coordinator
        self.registry = registry
        self.release_id = release.release_id
        self.flow_ids = {flow["id"] for flow in config["flows"]}
        self.operator_catalog = {}
        for ref, operator in registry.operators.items():
            name = ref.rsplit("@", 1)[0]
            source = Path(operator.source_file) if operator.source_file else None
            self.operator_catalog[name] = {
                "ref": ref, "definition": operator,
                "entry_function": operator.method.__name__,
                "code": source.read_text(encoding="utf-8") if source and source.is_file() else ""}

    def reload(self):
        # 释放旧协调器的 owner 租约再重建（同一 binding_id 重开分区）。
        if getattr(self, "coordinator", None) is not None:
            self.coordinator.close()
        if getattr(self, "provider", None) is not None:
            self.provider.close()
        self._load()

    # ---- 控制面下行 ---------------------------------------------------------

    def receive_config(self, payload: dict) -> dict:
        scenario_code = str(payload.get("scenario_code") or "").strip()
        version = str(payload.get("version") or "").strip()
        graph = payload.get("graph")
        config_hash = str(payload.get("config_hash") or "")
        if not scenario_code or not version or not isinstance(graph, (dict, list)):
            raise ValueError("scenario_code, version and graph are required")
        actual = config_content_hash(graph)
        if config_hash and config_hash != actual:
            raise ValueError(f"config_hash mismatch: declared {config_hash[:12]}, "
                             f"content {actual[:12]} (refuse tampered delivery)")
        flow_digest, skeleton_diagnostics = None, 0
        if _canvas_shaped(graph):
            from microflow.platform_graph import canvas_digest, convert_canvas_graph
            converted = convert_canvas_graph(graph, scenario_code)
            flow_digest = canvas_digest(converted["flow"])
            skeleton_diagnostics = len(converted["diagnostics"])
        self.configs[scenario_code] = {
            "version": version, "config_hash": actual, "flow_digest": flow_digest,
            "enable_saga_compensation": bool(payload.get("enable_saga_compensation")),
            "skeleton_diagnostics": skeleton_diagnostics}
        return {"accepted": True, "scenario_code": scenario_code, "version": version,
                "config_hash": actual, "flow_digest": flow_digest,
                "skeleton_diagnostics": skeleton_diagnostics,
                "note": "控制骨架已登记；可执行定义见本地项目（flow.id == scenario_code）"}

    def set_debug(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        self.debug_enabled = enabled
        return {"debug": enabled}

    # ---- 执行 ---------------------------------------------------------------

    async def execute_scenario(self, scenario_code: str, inputs: dict,
                               *, version: str | None = None) -> dict:
        config = self.configs.get(scenario_code)
        if config is None:
            raise LookupError(f"scenario {scenario_code!r} has no deployed config;"
                              " push it through the control plane first")
        if scenario_code not in self.flow_ids:
            raise LookupError(f"local project declares no flow {scenario_code!r};"
                              " convention: flow.id == scenario_code")
        request_id = digest({"execute": scenario_code, "config_hash": config["config_hash"],
                             "inputs": inputs})
        async with ScheduledRuntime(self.commands, record_sink=self.record_sink) as runtime:
            result = await runtime.run(scenario_code, inputs, request_id=request_id,
                                       timeout=self.execution_timeout)
            records = [thaw(record) for record in runtime.records]
        output = result["output"]
        error = output["error"]
        return {"status": result["status"],
                "version": version or config["version"],
                "final_output": output["data"],
                "error_message": (f"{error['code']}: {error['message']}" if error else ""),
                "execution_id": result["execution_id"],
                "config_hash": config["config_hash"],
                "records": records}

    # ---- 算子注册与试跑 ------------------------------------------------------

    def register_operator(self, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        code = str(payload.get("code") or "")
        version = str(payload.get("version") or "v1.0.0")
        if not _SAFE_NAME.match(name or ""):
            raise ValueError(f"operator name is not a safe file name: {name!r}")
        if not code.strip():
            raise ValueError("operator code is required")
        pushed_dir = self.project_path.parent / _PUSHED_DIR
        pushed_dir.mkdir(parents=True, exist_ok=True)
        target = pushed_dir / f"{name}.py"
        target.write_text(code, encoding="utf-8")
        try:
            self.reload()
        except MicroFlowError as error:
            target.unlink(missing_ok=True)
            self.reload()
            raise ValueError("pushed operator code does not satisfy the kernel contract "
                             "(must define register(registry) with schemas)") from error
        if name not in self.operator_catalog:
            target.unlink(missing_ok=True)
            self.reload()
            raise ValueError(f"pushed module loaded but did not register operator {name!r}")
        return {"registered": name, "version": version, "release_id": self.release_id}

    async def execute_operator(self, name: str, inputs: dict) -> dict:
        entry = self.operator_catalog.get(name)
        if entry is None:
            raise LookupError(f"operator {name!r} is not registered in this release")
        harness = self._harness_flow(name, entry["ref"], entry["definition"])
        # 单算子试跑是显式演练：CLI 同款 ephemeral 语义（本地同步运行器），
        # 不污染耐久状态；生命周期记录在 RunResult.records 里直接可用。
        ephemeral = compile_release(
            self.registry, [harness],
            defaults={"durability": "ephemeral", "recovery": {"enabled": False},
                      "persistence_binding": self.binding_id},
            source_file=str(self.project_path))
        outcome = await LocalRuntime(ephemeral).run_async(harness["id"], inputs)
        error = outcome.output["error"]
        return {"status": outcome.output["meta"]["status"],
                "final_output": outcome.output["data"],
                "error_message": (f"{error['code']}: {error['message']}" if error else ""),
                "records": [thaw(record) for record in outcome.records]}

    def _harness_flow(self, name: str, ref: str, definition) -> dict:
        """单算子试跑的显式约定：schema 必填字段直通（flow.input.X → 算子 → 输出）。"""
        def required_properties(schema_name: str) -> list[str]:
            schema = self.registry.schemas.get(schema_name)
            if not isinstance(schema, Mapping):
                return []
            properties = schema.get("properties") or {}
            return sorted(key for key in properties if key in set(schema.get("required") or ()))

        inputs = {key: {"from": f"flow.input.{key}", "required": True}
                  for key in required_properties(definition.input_schema)}
        outputs = {key: {"from": f"nodes.a.output.data.{key}", "required": True}
                   for key in required_properties(definition.output_schema)}
        return {"id": f"__op_{name}", "input_schema": definition.input_schema,
                "output_schema": definition.output_schema,
                "nodes": {"a": {"operator": ref, "inputs": inputs}},
                "outputs": outputs}
