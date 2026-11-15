"""Parse the declarative MicroFlow DSL without executing Python code."""
import ast

from .errors import ContractError
from .values import validate_value


def parse_project(text: str) -> dict:
    """Return the existing project model from a restricted .mf source file."""
    if len(text.encode("utf-8")) > 4_194_304:
        raise ContractError("CONFIG_LIMIT", "Configuration exceeds byte budget")
    try:
        tree = ast.parse(text, mode="exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ContractError("INVALID_PROJECT", "Invalid DSL syntax", line=getattr(exc, "lineno", None),
                            column=getattr(exc, "offset", None)) from exc

    def fail(node, message):
        raise ContractError("INVALID_PROJECT", message, line=getattr(node, "lineno", 0),
                            column=getattr(node, "col_offset", 0) + 1)

    def call(node, name=None):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            fail(node, "Expected a DSL declaration")
        if name is not None and node.func.id != name:
            fail(node, f"Expected {name}")
        if any(k.arg is None for k in node.keywords):
            fail(node, "Keyword expansion is not allowed")
        names = [k.arg for k in node.keywords]
        if len(set(names)) != len(names):
            fail(node, "Duplicate keyword")
        return node.func.id, [value(a) for a in node.args], {k.arg: value(k.value) for k in node.keywords}

    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool, type(None)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = value(node.operand)
            if type(v) in (int, float):
                return -v
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value(x) for x in node.elts]
        if isinstance(node, ast.Dict):
            result = {}
            for k, v in zip(node.keys, node.values):
                key = value(k) if k is not None else None
                if type(key) is not str or key in result:
                    fail(node, "Dictionary keys must be unique strings")
                result[key] = value(v)
            return result
        if isinstance(node, ast.Call):
            name, args, kwargs = call(node)
            if name == "source" and len(args) == 1 and type(args[0]) is str and set(kwargs) <= {"required", "default"}:
                return {"from": args[0], **kwargs}
            if name == "path" and len(args) == 1 and type(args[0]) is str and not kwargs:
                return {"path": args[0]}
            if name in ("exists", "truthy", "not_") and len(args) == 1 and not kwargs:
                return {"not" if name == "not_" else name: args[0]}
            if name in ("eq", "ne", "lt", "lte", "gt", "gte", "in_") and len(args) == 2 and not kwargs:
                return {"in" if name == "in_" else name: args}
            if name in ("all_", "any_") and args and not kwargs:
                return {"and" if name == "all_" else "or": args}
        fail(node, "Unsupported DSL expression")

    project = {"modules": [], "flows": []}
    flow_ids = set()
    for statement in tree.body:
        if isinstance(statement, ast.Expr):
            name, args, kwargs = call(statement.value)
            if name == "module" and len(args) == 1 and type(args[0]) is str and not kwargs:
                project["modules"].append(args[0])
            elif name == "defaults" and not args and "defaults" not in project:
                project["defaults"] = kwargs
            else:
                fail(statement, "Expected module(...) or defaults(...)")
        elif isinstance(statement, ast.With) and len(statement.items) == 1 and statement.items[0].optional_vars is None:
            _, args, kwargs = call(statement.items[0].context_expr, "flow")
            if len(args) != 1 or type(args[0]) is not str or args[0] in flow_ids:
                fail(statement, "flow requires a unique string id")
            if set(kwargs) - {"input_schema", "output_schema", "options"}:
                fail(statement, "Unknown flow argument")
            flow_ids.add(args[0])
            flow = {"id": args[0], **kwargs, "nodes": {}, "outputs": {}}
            for entry in statement.body:
                if not isinstance(entry, ast.Expr):
                    fail(entry, "Expected a node or output declaration")
                name, args, kwargs = call(entry.value)
                if name == "output":
                    if len(args) != 2 or any(type(a) is not str for a in args) or set(kwargs) - {"required", "default"}:
                        fail(entry, "output requires a target and source path")
                    if args[0] in flow["outputs"]:
                        fail(entry, "Duplicate output target")
                    flow["outputs"][args[0]] = {"from": args[1], **kwargs}
                elif name in ("operator", "subflow", "route", "join", "map", "loop", "wait"):
                    if len(args) != 1 or type(args[0]) is not str or args[0] in flow["nodes"]:
                        fail(entry, "Node requires a unique string id")
                    if "type" in kwargs or ("when" in kwargs and "condition" in kwargs):
                        fail(entry, "Conflicting node arguments")
                    if "when" in kwargs:
                        kwargs["condition"] = kwargs.pop("when")
                    flow["nodes"][args[0]] = {"type": name, **kwargs}
                else:
                    fail(entry, "Unknown DSL declaration")
            project["flows"].append(flow)
        else:
            fail(statement, "Only module, defaults and flow declarations are allowed")
    validate_value(project)
    return project
