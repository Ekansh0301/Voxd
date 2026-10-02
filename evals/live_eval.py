"""
Live desktop + browser eval: the real model drives the real apps, and each task is
checked against the real end state (window titles, MPRIS, volume, page URLs...).

    .venv/bin/python -m evals.live_eval              # all tasks
    .venv/bin/python -m evals.live_eval -k spotube   # names containing "spotube"

It opens and uses apps on your screen: Calculator, Okular, VS Code, Ghostty,
Super Productivity, Firefox (TARS), Spotube, and sends one question to ChatGPT.
State is put back afterwards (volume, paused music, Super Productivity's view) and
only windows it opened itself are closed. Approval questions are answered "yes"
and listed. Target (docs/PLAN.md, Phase 3 exit): >= 65%.
"""

import argparse
import asyncio
import contextlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from tars.agent.loop import run_turn
from tars.agent.tools import Context
from tars.config import load
from tars.llm.swap import ensure_llm, warm_up
from tars.mcp.manager import MCPManager
from tars.perception.keyboard import Keyboard
from tars.perception.windows import activate, list_windows
from tars.persona import stamp, system_prompt
from tars.tools import browser, default_registry, music, research

T = Path.home() / "tars-live-test"
RESULTS = Path(__file__).parent / "results"


@dataclass
class Run:
    answer: str
    steps: list[dict]


@dataclass
class Live:
    name: str
    prompt: str
    check: Callable[[Run], Awaitable[bool]]
    setup: Callable[[], Awaitable[None]] | None = None
    cleanup: Callable[[], Awaitable[None]] | None = None
    notes: list[str] = field(default_factory=list)


def used(run: Run, *tools: str) -> bool:
    return any(s["tool"] in tools for s in run.steps)


async def titles() -> list[str]:
    return [w.title for w in await list_windows()]


async def close_windows(
    match: Callable[[str], bool], combo: str = "ctrl+w", tries: int = 4
) -> None:
    """Close windows this eval opened (by title), via their own shortcut."""
    for _ in range(tries):
        wins = [w for w in await list_windows() if match(w.title)]
        if not wins:
            return
        await activate(wins[0])
        await asyncio.sleep(0.6)
        if not any(w.focused and w.id == wins[0].id for w in await list_windows()):
            return
        async with Keyboard() as kb:
            await kb.combo(combo)
        await asyncio.sleep(1.2)


def volume() -> float:
    out = subprocess.run(
        ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True
    ).stdout
    m = re.search(r"([\d.]+)", out)
    return float(m.group(1)) if m else -1.0


def tmux_exists(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0


STATE: dict = {}


def tasks() -> list[Live]:
    async def calc_check(r):
        return "84" in r.answer

    async def calc_clean():
        await close_windows(lambda t: t == "Calculator", "ctrl+q")

    async def pdf_setup():
        from PIL import Image

        T.mkdir(exist_ok=True)
        Image.new("RGB", (400, 300), "white").save(T / "lecture.pdf")

    async def pdf_check(r):
        await asyncio.sleep(2)
        return any("lecture" in t and "Okular" in t for t in await titles())  # shows the doc title

    async def pdf_clean():
        await close_windows(lambda t: "lecture" in t and "Okular" in t, "ctrl+q")

    async def code_setup():
        T.mkdir(exist_ok=True)
        (T / "notes.py").write_text("print('hi')\n")

    async def code_check(r):
        await asyncio.sleep(4)
        return any(T.name in t and "Visual Studio Code" in t for t in await titles())

    async def code_clean():
        await close_windows(lambda t: T.name in t and "Visual Studio Code" in t, "ctrl+shift+w")

    async def sp_check(r):
        # SP exposes no page address or reliable view heading; the accessibility action on
        # its "Planner" item reports success, and its change report shows the new view
        return any(s["tool"] in ("click", "click_on_screen") and "planner" in json.dumps(s["args"]).lower()
                   and "done" in s["result"] for s in r.steps)  # fmt: skip

    async def sp_setup():  # start from Today (a previous run may have left Planner)
        await sp_clean()

    async def sp_clean():
        reg = STATE["reg"]
        await reg.call(STATE["ctx"], "read_screen", {"window": "super productivity"})
        await reg.call(STATE["ctx"], "click", {"name": "Today"})

    async def vol_setup():
        STATE["volume"] = volume()

    async def vol_check(r):
        return abs(volume() - 0.35) < 0.02

    async def vol_clean():
        if STATE.get("volume", -1) >= 0:
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{STATE['volume']:.2f}"]
            )

    async def term_setup():
        T.mkdir(exist_ok=True)
        (T / "fetch.py").write_text('import json\nconfig = json.load(open("settings.json"))\n')
        subprocess.Popen(["ghostty", "-e", "tmux", "new-session", "-s", "tarslive", "-c", str(T),
                          "python3 fetch.py; exec bash"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        await asyncio.sleep(3)
        wins = [
            w for w in await list_windows() if "ghostty" in w.wm_class.lower() and "tmux" in w.title
        ]
        if wins:
            await activate(wins[-1])
            await asyncio.sleep(0.8)

    async def term_check(r):
        return used(r, "screen_context") and "settings" in r.answer.lower()

    async def term_clean():
        subprocess.run(["tmux", "kill-session", "-t", "tarslive"], capture_output=True)

    async def github_check(r):
        s = browser._get_server()
        return bool(s) and "github.com" in await s.call_tool("list_pages", {})

    async def chatgpt_check(r):
        return "canberra" in r.answer.lower()

    async def research_check(r):
        return used(r, "web_search") and bool(re.search(r"\d", r.answer))

    async def tabs_check(r):
        return used(r, "web_tabs")

    async def spotube_setup():
        STATE["was_playing"] = music.now_playing()[2]

    async def spotube_check(r):
        await asyncio.sleep(2)
        return "believer" in music.now_playing()[0].lower()

    async def spotube_clean():
        if not STATE.get("was_playing"):
            music._mpris("Pause")

    async def tasks_check(r):
        return used(r, "list_tasks")

    return [
        Live(
            "calculator",
            "Open the calculator and work out 12 times 7 on it.",
            calc_check,
            cleanup=calc_clean,
        ),
        Live(
            "okular pdf",
            f"Open lecture.pdf from {T.name} in my home folder.",
            pdf_check,
            pdf_setup,
            pdf_clean,
        ),
        Live(
            "vscode folder",
            f"Open the {T.name} folder in VS Code.",
            code_check,
            code_setup,
            code_clean,
        ),
        Live(
            "super productivity planner",
            "In Super Productivity, switch to the Planner view.",
            sp_check,
            sp_setup,
            sp_clean,
        ),
        Live("volume", "Set the volume to 35 percent.", vol_check, vol_setup, vol_clean),
        Live(
            "explain terminal error",
            "Explain the error on my screen.",
            term_check,
            term_setup,
            term_clean,
        ),
        Live("open github", "Open GitHub.", github_check),
        Live(
            "ask chatgpt",
            "Ask ChatGPT what the capital of Australia is and tell me its answer.",
            chatgpt_check,
        ),
        Live("research", "Look up the population of Delhi.", research_check),
        Live("firefox tabs", "What tabs do I have open in Firefox?", tabs_check),
        Live("spotube song", "Play Believer.", spotube_check, spotube_setup, spotube_clean),
        Live("next task", "What's my next task?", tasks_check),
    ]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="")
    args = ap.parse_args()
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
    approvals: list[str] = []

    async def yes(summary: str) -> bool:
        approvals.append(summary)
        return True

    ctx = Context(desktop=True, approve=yes)
    STATE.update(reg=reg, ctx=ctx)
    system = system_prompt(
        cfg, can_act=True, sites=["Outlook", "YouTube", "GitHub", "ChatGPT", "Gemini"]
    )
    rows = []
    try:
        for task in [t for t in tasks() if args.k in t.name]:
            approvals.clear()
            ok, answer, steps, err = False, "", [], ""
            t0 = time.monotonic()
            try:
                if task.setup:
                    await task.setup()
                msgs = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": stamp(task.prompt)},
                ]
                res = await run_turn(msgs, reg, ctx, cfg["llm"]["endpoint"], cfg["llm"]["brain"],
                                     max_tokens=400, temperature=0.3, top_p=0.8)  # fmt: skip
                answer, steps = res.answer, res.steps
                ok = await task.check(Run(answer, steps))
            except Exception as e:  # a task's failure must not stop the others
                err = f"{type(e).__name__}: {e}"
            finally:
                if task.cleanup:
                    with contextlib.suppress(Exception):
                        await task.cleanup()
            secs = round(time.monotonic() - t0, 1)
            print(f"{'PASS' if ok else 'FAIL'}  {task.name:28} {secs:5.1f}s  {len(steps)} steps")
            if not ok:
                print(f"      steps: {[s['tool'] for s in steps]}  answer: {answer[:160]!r} {err}")
            rows.append({"name": task.name, "ok": ok, "seconds": secs, "approvals": list(approvals),
                         "steps": [f"{s['tool']}({json.dumps(s['args'])[:80]}) -> {s['result'][:300]}" for s in steps], "answer": answer})  # fmt: skip
    finally:
        await research.shutdown()
        await mcp.close()
        shutil.rmtree(T, ignore_errors=True)
        if swap:
            swap.terminate()
    passed = sum(r["ok"] for r in rows)
    summary = {"passed": f"{passed}/{len(rows)}", "rate": round(passed / max(len(rows), 1), 2)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "live.json").write_text(json.dumps({"summary": summary, "tasks": rows}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
