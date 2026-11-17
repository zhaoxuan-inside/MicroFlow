"""MicroFlow MCP bridge: expose the framework CLI as callable MCP tools.

The framework CLI is the single contract surface for VibeCoding tools; this
bridge wraps it as an MCP (Model Context Protocol) tool server so coding
agents can call `check` / `run` / `context` / `scaffold` directly. Design
constraint (archived CLI command-system design, section 1.1): protocol
adapters stay OUTSIDE the zero-dependency framework — the kernel never learns
about MCP, and this package depends on nothing beyond the standard library.

Wire format: newline-delimited JSON-RPC 2.0 over stdio (MCP stdio transport),
tools-only surface: initialize, notifications/initialized, ping, tools/list,
tools/call. Every tool wraps exactly one CLI invocation (argv passing, no
shell), forwards the CLI's deterministic JSON envelope verbatim, and maps the
shared exit codes (0 = affirmative, 1 = object-negative, 2 = request failed)
onto MCP `isError`.
"""
import json
import sys

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "microflow-mcp", "version": "0.1.0"}


def _reply(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def handle_message(message, tools, *, protocol_version=PROTOCOL_VERSION):
    """One JSON-RPC message in, one response dict out (None for notifications)."""
    if not isinstance(message, dict):
        return _error(None, -32600, "Request must be an object")
    method = message.get("method")
    request_id = message.get("id")
    if method is None:
        return _error(request_id, -32600, "Missing method")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion", protocol_version)
        return _reply(request_id, {
            "protocolVersion": requested if isinstance(requested, str) else protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO})
    if method == "ping":
        return _reply(request_id, {})
    if method == "tools/list":
        return _reply(request_id, {"tools": [
            {"name": tool.name, "description": tool.description,
             "inputSchema": tool.schema} for tool in tools]})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        for tool in tools:
            if tool.name == name:
                return _reply(request_id, tool.invoke(arguments))
        return _error(request_id, -32602, f"Unknown tool: {name}")
    return _error(request_id, -32601, f"Method not found: {method}")


def serve(tools, *, stdin=None, stdout=None):
    """Blocking stdio loop: newline-delimited JSON-RPC in, replies out."""
    stream_in, stream_out = stdin or sys.stdin, stdout or sys.stdout
    for line in stream_in:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = _error(None, -32700, "Invalid JSON")
        else:
            response = handle_message(message, tools)
        if response is not None:
            stream_out.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
            stream_out.flush()
