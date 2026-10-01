import asyncio
import sys
from pathlib import Path

from tars.agent.tools import Context, Registry, Tier
from tars.mcp.manager import MCPManager

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


def test_tools_register_with_tiers_and_run(tmp_path):
    async def go():
        cfg = {"mcpServers": {"fake": {"command": sys.executable, "args": [FAKE]}}}
        mgr, reg = MCPManager(cfg), Registry()
        names = await mgr.start(reg)
        ctx = Context(home=tmp_path, approve=None, desktop=False)  # None: deny approvals
        echo = await reg.call(ctx, "fake_echo", {"text": "hi"})
        wipe = await reg.call(ctx, "fake_wipe", {})
        await mgr.close()
        return names, reg, echo, wipe

    names, reg, echo, wipe = asyncio.run(go())
    assert set(names) == {"fake_echo", "fake_wipe", "fake_mystery"}
    assert reg.tools["fake_echo"].tier == Tier.T0
    assert reg.tools["fake_wipe"].tier == Tier.T2
    assert reg.tools["fake_mystery"].tier == Tier.T2  # unknown -> asks first
    assert reg.tools["fake_echo"].description == "Echo text back."
    assert echo == "echo: hi"
    assert wipe.startswith("refused")  # T2 and nobody approved


def test_allow_list_and_dead_server(tmp_path):
    async def go():
        cfg = {"mcpServers": {
            "fake": {"command": sys.executable, "args": [FAKE], "tools": ["echo"]},
            "dead": {"command": "/nonexistent/server"},
        }}  # fmt: skip
        mgr, reg = MCPManager(cfg), Registry()
        names = await mgr.start(reg)
        await mgr.close()
        return names

    assert asyncio.run(go()) == ["fake_echo"]
