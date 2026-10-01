"""
Local WebSocket the voice service publishes to and the avatar window reads.

Bound to 127.0.0.1 and protected by a random per-run token, because state
messages include what you said.
"""

import asyncio
import json
import logging
import secrets

import websockets

log = logging.getLogger("tars.ui.bus")


class UiBus:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host, self.port = host, port
        self.token = secrets.token_urlsafe(16)
        self._clients: set = set()
        self._last_state: str | None = None
        self._server = None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/?token={self.token}"

    async def start(self):
        self._server = await websockets.serve(self._handler, self.host, self.port)
        log.info(f"avatar bus on ws://{self.host}:{self.port}")

    async def _handler(self, ws):
        if ws.request.path != f"/?token={self.token}":
            await ws.close(code=4401, reason="bad token")
            return
        self._clients.add(ws)
        try:
            if self._last_state:
                await ws.send(self._last_state)
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)

    def publish(self, msg: dict):
        data = json.dumps(msg)
        if msg.get("type") == "state":
            self._last_state = data
        for ws in list(self._clients):
            asyncio.ensure_future(self._send(ws, data))

    async def _send(self, ws, data: str):
        try:
            await ws.send(data)
        except websockets.ConnectionClosed:
            self._clients.discard(ws)

    async def close(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
