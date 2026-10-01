"""
Minimal MCP client over stdio (JSON-RPC 2.0, one JSON message per line).

Covers what TARS needs from a tool server: initialize, tools/list (paginated)
and tools/call. Requests the server sends us (sampling, roots, elicitation) are
answered with "method not found"; notifications are logged and ignored.
"""

import asyncio
import contextlib
import itertools
import json
import logging
import os
import signal

from tars import TARS_HOME

log = logging.getLogger("tars.mcp")
PROTOCOL = "2025-06-18"


class MCPError(Exception):
    pass


class MCPServer:
    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | None = None):  # fmt: skip
        self.name, self.command, self.args = name, command, args or []
        self.env, self.cwd = env or {}, cwd
        self.proc: asyncio.subprocess.Process | None = None
        self.info: dict = {}
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def start(self, timeout: float = 60):
        logdir = TARS_HOME / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        stderr = open(logdir / f"mcp-{self.name}.log", "ab")
        self.proc = await asyncio.create_subprocess_exec(
            self.command, *self.args, cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
            env={**os.environ, **self.env}, limit=16 * 1024 * 1024,
            start_new_session=True,  # Ctrl+C goes to TARS, which closes servers itself
        )  # fmt: skip
        self._reader = asyncio.create_task(self._read())
        self.info = await self.request(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {},
             "clientInfo": {"name": "tars", "version": "0.1"}},
            timeout=timeout,
        )  # fmt: skip
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        log.info(f"{self.name}: {self.info.get('serverInfo', {}).get('name', '?')} ready")

    async def _send(self, msg: dict):
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def _read(self):
        assert self.proc and self.proc.stdout
        while line := await self.proc.stdout.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.debug(f"{self.name}: non-JSON line {line[:120]!r}")
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg)
            elif "id" in msg and "method" in msg:  # server -> client request
                await self._send({"jsonrpc": "2.0", "id": msg["id"],
                                  "error": {"code": -32601, "message": "not supported by TARS"}})  # fmt: skip
        for fut in self._pending.values():  # server exited
            if not fut.done():
                fut.set_exception(MCPError(f"{self.name} exited"))

    async def request(self, method: str, params: dict | None = None, timeout: float = 120) -> dict:
        rid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        try:
            msg = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)
        if "error" in msg:
            raise MCPError(f"{self.name} {method}: {msg['error'].get('message', msg['error'])}")
        return msg["result"]  # type: ignore[no-any-return]

    async def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            res = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, name: str, arguments: dict, timeout: float = 120) -> str:
        res = await self.request("tools/call", {"name": name, "arguments": arguments}, timeout)
        parts = []
        for c in res.get("content", []):
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource" and "text" in c.get("resource", {}):
                parts.append(c["resource"]["text"])
            else:
                parts.append(f"[{c.get('type', 'content')} omitted]")
        if not parts and "structuredContent" in res:
            parts.append(json.dumps(res["structuredContent"]))
        text = "\n".join(parts) or "(no output)"
        return f"error: {text}" if res.get("isError") else text

    async def close(self):
        if self.proc and self.proc.returncode is None:
            # The server runs in its own session (e.g. npx -> node): stop the whole group.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
        if self._reader:
            self._reader.cancel()
