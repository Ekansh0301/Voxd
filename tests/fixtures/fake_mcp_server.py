"""A tiny stdio MCP server for tests: tools `echo` (read-only) and `wipe` (destructive)."""

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back. It is very useful. Second sentence ignored.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "wipe",
        "description": "Deletes things.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "mystery",
        "description": "No annotations.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

result: dict
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue  # notification
    method, rid = msg["method"], msg["id"]
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg["params"]
        if p["name"] == "echo":
            result = {"content": [{"type": "text", "text": "echo: " + p["arguments"]["text"]}]}
        else:
            result = {"content": [{"type": "text", "text": "nope"}], "isError": True}
    else:
        print(
            json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no"}}),
            flush=True,
        )
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}), flush=True)
