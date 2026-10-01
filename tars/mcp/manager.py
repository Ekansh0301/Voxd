"""
Start the MCP servers in config/mcp.json and expose their tools to the agent.

Config uses the same shape as Claude Desktop, plus optional TARS keys:

    {"mcpServers": {
        "firefox": {"command": "npx", "args": ["@mozilla/firefox-devtools-mcp", "--connect-existing"],
                    "enabled": true,
                    "tools": ["navigate", "snapshot"],        # optional allow-list
                    "tiers": {"navigate": "T1"}}}}             # optional per-tool tier override

Tiers come from each tool's annotations when the server provides them
(readOnlyHint -> T0, destructiveHint -> T2); anything else defaults to T2, so
an unknown tool always asks first.
"""

import json
import logging
import re
from pathlib import Path

from tars.agent.tools import Context, Registry, Tier
from tars.config import USER
from tars.mcp.client import MCPServer

log = logging.getLogger("tars.mcp")
DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "mcp.json"
USER_MCP = USER.parent / "mcp.json"


def tier_for(tool: dict, override: str | None = None) -> Tier:
    if override:
        return Tier[override]
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is True:
        return Tier.T0
    if ann.get("destructiveHint") is True:
        return Tier.T2
    if ann.get("destructiveHint") is False and ann.get("openWorldHint") is False:
        return Tier.T1  # local and non-destructive
    return Tier.T2


def compact(description: str, limit: int = 160) -> str:
    """Third-party descriptions can be paragraphs; a 4B model needs one line."""
    first = re.split(r"(?<=[.!?])\s|\n", (description or "").strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1] + "…"


def _schema(schema: dict | None) -> dict:
    s = dict(schema or {"type": "object", "properties": {}})
    props = {}
    for name, p in (s.get("properties") or {}).items():
        p = dict(p)
        if "description" in p:
            p["description"] = compact(p["description"], 100)
        props[name] = p
    s["properties"] = props
    s.setdefault("type", "object")
    return s


def load_config() -> dict:
    cfg: dict = {"mcpServers": {}}
    for path in (DEFAULT, USER_MCP):
        if path.exists():
            cfg["mcpServers"].update(json.loads(path.read_text()).get("mcpServers", {}))
    return cfg


class MCPManager:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else load_config()
        self.servers: dict[str, MCPServer] = {}

    async def start(self, registry: Registry) -> list[str]:
        """Start enabled servers and register their tools; returns registered names."""
        added = []
        for name, spec in self.config.get("mcpServers", {}).items():
            if not spec.get("enabled", True):
                continue
            server = MCPServer(
                name, spec["command"], spec.get("args"), spec.get("env"), spec.get("cwd")
            )
            try:
                await server.start()
                tools = await server.list_tools()
            except Exception as e:
                log.warning(f"MCP server {name} unavailable: {e}")
                await server.close()
                continue
            self.servers[name] = server
            allow = set(spec.get("tools") or [t["name"] for t in tools])
            for t in tools:
                if t["name"] in allow:
                    added.append(self._register(registry, name, server, t, spec.get("tiers", {})))
        return added

    def _register(self, registry: Registry, sname: str, server: MCPServer, tool: dict,
                  tiers: dict) -> str:  # fmt: skip
        local = re.sub(r"[^a-zA-Z0-9_]", "_", f"{sname}_{tool['name']}")[:64]
        remote = tool["name"]

        async def handler(ctx: Context, **args) -> str:
            return await server.call_tool(remote, args)

        registry.tool(local, compact(tool.get("description", "")), _schema(tool.get("inputSchema")),
                      tier=tier_for(tool, tiers.get(remote)))(handler)  # fmt: skip
        return local

    async def close(self):
        for s in self.servers.values():
            await s.close()
