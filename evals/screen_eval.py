"""
Live screen eval: "Explain the error on my screen" with the real model, real apps.

    .venv/bin/python -m evals.screen_eval            # terminal, vscode, firefox
    .venv/bin/python -m evals.screen_eval terminal   # one scene

Opens windows on your screen: a Ghostty terminal (tmux session "tarstest") with a
crashing script, a VS Code window with a syntax error, and a Firefox tab with a
deploy error page, all from a temporary folder in your home. Approvals are
refused, so nothing is changed. Afterwards it closes what it opened (only
windows whose titles name the test folder) and deletes the folder.
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from tars.agent.loop import run_turn
from tars.agent.tools import Context
from tars.config import load
from tars.llm.swap import ensure_llm, warm_up
from tars.mcp.manager import MCPManager
from tars.perception.windows import activate, find, list_windows
from tars.persona import stamp, system_prompt
from tars.tools import browser, default_registry

T = Path.home() / "tars-screen-test"
CHECKS = {
    "terminal": ("settings.json", "filenotfound"),
    "vscode": ("colon", "line 3"),
    "firefox": ("prod.json", "config"),
}
FILES = {
    "fetch.py": 'import json\n\ndef load(path):\n    with open(path) as f:\n        return json.load(f)\n\nconfig = load("settings.json")\nprint(config["name"])\n',
    "broken.py": "def total(prices):\n    result = 0\n    for p in prices\n        result += p\n    return result\n",
    "page.html": "<!doctype html><title>Build failed</title><h1>Deploy failed</h1><pre>Error: ENOENT: no such file or directory, open '/app/config/prod.json'\n    at loadConfig (/app/src/config.js:12:18)</pre>",
}

SCENES = sys.argv[1:] or ["terminal", "vscode", "firefox"]


async def front(name, tries=30):
    for _ in range(tries):
        w = find(name, await list_windows())
        if w:
            await activate(w)
            await asyncio.sleep(0.8)
            return find(name, await list_windows())
        await asyncio.sleep(0.5)


async def main():
    cfg = load()
    swap = await ensure_llm(cfg["llm"]["endpoint"])
    await warm_up(cfg["llm"]["endpoint"], cfg["llm"]["brain"])
    reg = default_registry()
    mcp = MCPManager()
    browser.register(reg, lambda: mcp.servers.get("firefox"))
    await mcp.start(reg)
    for _ in range(60):
        if browser._get_server() and browser._get_server().proc:
            break
        await asyncio.sleep(0.5)
    ctx = Context(desktop=True)  # approve=None: anything needing approval is refused
    T.mkdir(exist_ok=True)
    for name, body in FILES.items():
        (T / name).write_text(body)
    passed = 0
    try:
        for scene in SCENES:
            if scene == "terminal":
                subprocess.Popen(
                    [
                        "ghostty",
                        "-e",
                        "tmux",
                        "new-session",
                        "-s",
                        "tarstest",
                        "-c",
                        str(T),
                        "python3 fetch.py; exec bash",
                    ],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await asyncio.sleep(3)
                w = await front("tarstest") or await front("ghostty")
            elif scene == "vscode":
                subprocess.run(["code", "-n", str(T)])
                await asyncio.sleep(4)
                subprocess.run(["code", "-g", f"{T}/broken.py:3"])
                await asyncio.sleep(3)
                w = await front("tars-screen-test")
            else:
                await reg.call(ctx, "open_url", {"url": f"file://{T}/page.html"})
                await asyncio.sleep(2)
                w = await front("firefox")
            print(f"\n=== {scene}: front window = {w.label if w else None}")
            msgs = [
                {
                    "role": "system",
                    "content": system_prompt(cfg, can_act=True, sites=["ChatGPT", "YouTube"]),
                },
                {"role": "user", "content": stamp("Explain the error on my screen.")},
            ]
            t = time.monotonic()
            res = await run_turn(
                msgs,
                reg,
                ctx,
                cfg["llm"]["endpoint"],
                cfg["llm"]["brain"],
                max_tokens=400,
                temperature=0.3,
                top_p=0.8,
            )
            for st in res.steps:
                print(
                    "  ·",
                    st["tool"],
                    str(st["args"])[:80],
                    "->",
                    st["result"][:160].replace("\n", " | "),
                )
            ok = any(st["tool"] == "screen_context" for st in res.steps)
            ok = ok and any(k in res.answer.lower() for k in CHECKS[scene])
            passed += ok
            print(f"  {'PASS' if ok else 'FAIL'} ({time.monotonic()-t:.1f}s): {res.answer}")
        print(f"\n{passed}/{len(SCENES)} scenes explained")
    finally:
        await cleanup(reg)
        await mcp.close()
        if swap:
            swap.terminate()


async def cleanup(reg):
    import shutil

    from tars.perception.keyboard import Keyboard

    subprocess.run(["tmux", "kill-session", "-t", "tarstest"], capture_output=True)
    for _ in range(4):  # VS Code windows on the test folder only
        test = [
            w for w in await list_windows() if T.name in w.title and "Visual Studio Code" in w.title
        ]
        if not test:
            break
        await activate(test[0])
        await asyncio.sleep(0.6)
        if not any(w.focused and w.id == test[0].id for w in await list_windows()):
            break
        async with Keyboard() as kb:
            await kb.combo("ctrl+shift+w")
        await asyncio.sleep(1.5)
    s = browser._get_server()
    if s is not None:
        pages = await s.call_tool("list_pages", {})
        if T.name in pages:
            await s.call_tool("navigate_page", {"url": "about:blank"})
    shutil.rmtree(T, ignore_errors=True)


asyncio.run(main())
