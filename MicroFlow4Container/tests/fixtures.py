"""共享夹具：一个可执行的容器本地项目（flow.id == scenario_code 约定）。"""
import json
from pathlib import Path

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}

MODULE = '''
def increment(input, output, context, metrix, debug, log):
    """adds one"""
    output.set("n", input["n"] + 1)
    return True


def register(registry):
    registry.register_schema("ints", %s)
    registry.register_operator(name="increment", version="1", method=increment,
                               input_schema="ints", output_schema="ints",
                               description="adds one")
''' % json.dumps(SCHEMA)

PROJECT = {
    "modules": ["ops.py"],
    "defaults": {},
    "flows": [{"id": "SC_INC", "input_schema": "ints", "output_schema": "ints",
               "nodes": {"a": {"operator": "increment@1",
                               "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
               "outputs": {"n": {"from": "nodes.a.output.data.n", "required": True}}}],
}

CANVAS_GRAPH = {"entry_node": "a", "exit_node": "a",
                "nodes": [{"id": "a", "kind": "OPERATOR", "operator": "increment",
                           "operator_version": "1"}],
                "edges": []}


def write_project(root: Path, *, module: str = MODULE, project: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "ops.py").write_text(module, encoding="utf-8")
    path = root / "project.json"
    path.write_text(json.dumps(project or PROJECT), encoding="utf-8")
    return path
