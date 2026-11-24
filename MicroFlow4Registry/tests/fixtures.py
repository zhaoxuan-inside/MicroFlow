"""Shared fixtures: a minimal, real MicroFlow project built through the CLI."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_SRC = ROOT.parent / "MicroFlow4Python" / "src"

SCHEMAS = {
    "ints": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
}

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
''' % json.dumps(SCHEMAS["ints"])

PROJECT = {
    "modules": ["ops.py"],
    "flows": [{
        "id": "main", "input_schema": "ints", "output_schema": "ints",
        "nodes": {"a": {"operator": "increment@1",
                        "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
        "outputs": {"n": {"from": "nodes.a.output.data.n", "required": True}},
    }],
}


def cli_env() -> dict:
    """Environment that makes ``python -m microflow`` resolvable in child processes."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYTHON_SRC) + (os.pathsep + env["PYTHONPATH"]
                                           if env.get("PYTHONPATH") else "")
    env["MF_REGISTRY_CLI"] = f"{sys.executable} -m microflow"
    return env


def write_project(root: Path, *, module: str = MODULE, project: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "ops.py").write_text(module, encoding="utf-8")
    path = root / "project.json"
    path.write_text(json.dumps(project or PROJECT), encoding="utf-8")
    return path
