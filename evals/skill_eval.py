"""
Learned-routine eval (Phase 4 exit: tasks with a routine >= 90% right and much faster).

    .venv/bin/python -m evals.skill_eval

For each task: run it once (TARS learns the routine), then run variants that should
replay it. Checks the real result each time and compares the times. Uses a
throwaway routine store, so your own routines are untouched. Opens Super
Productivity and Firefox (TARS), and asks ChatGPT three short questions.
"""

import asyncio
import json
import tempfile
import time
from pathlib import Path

from tars.agent.tools import Context
from tars.config import load
from tars.llm.swap import ensure_llm, warm_up
from tars.mcp.manager import MCPManager
from tars.persona import stamp, system_prompt
from tars.skills import Skills
from tars.skills.runner import turn_with_skills
from tars.tools import browser, default_registry, research

RESULTS = Path(__file__).parent / "results"


def clicked(name: str):
    def check(answer: str, steps: list[dict]) -> bool:
        return any(
            s["tool"] == "click" and name in json.dumps(s["args"]).lower() and "done" in s["result"]
            for s in steps
        )

    return check


def says(word: str):
    return lambda answer, steps: word in answer.lower()


TASKS = [  # (first request, its check, [(variant, check), ...])
    ("In Super Productivity, switch to the Planner view.", clicked("planner"),
     [("In Super Productivity, switch to the Today view.", clicked("today")),
      ("In Super Productivity, switch to the Planner view.", clicked("planner"))]),
    ("Ask ChatGPT what the capital of Australia is and tell me its answer.", says("canberra"),
     [("Ask ChatGPT what the capital of Japan is and tell me its answer.", says("tokyo")),
      ("Ask ChatGPT what the capital of France is and tell me its answer.", says("paris"))]),
]  # fmt: skip


async def main():
    cfg = load()
    swap = await ensure_llm(cfg["llm"]["endpoint"])
    await warm_up(cfg["llm"]["endpoint"], cfg["llm"]["brain"])
    with tempfile.TemporaryDirectory(prefix="tars-skills-") as tmp:
        skills = Skills(Path(tmp) / "skills.db")
        reg = default_registry(skills=skills)
        mcp = MCPManager()
        browser.register(reg, lambda: mcp.servers.get("firefox"))
        await mcp.start(reg)
        for _ in range(60):
            if browser._get_server() and browser._get_server().proc:
                break
            await asyncio.sleep(0.5)

        async def yes(_summary: str) -> bool:
            return True

        ctx = Context(desktop=True, approve=yes)
        system = system_prompt(cfg, can_act=True, sites=["ChatGPT", "GitHub", "YouTube"])
        rows = []

        async def run(request: str, check) -> dict:
            msgs = [
                {"role": "system", "content": system},
                {"role": "user", "content": stamp(request)},
            ]
            t0 = time.monotonic()
            res, used, outcome = await turn_with_skills(skills, request, msgs, reg, ctx, cfg["llm"]["endpoint"],
                                                        cfg["llm"]["brain"], max_tokens=300, temperature=0.3, top_p=0.8)  # fmt: skip
            secs = round(time.monotonic() - t0, 1)
            ok = check(res.answer, res.steps)
            row = {"request": request, "ok": ok, "seconds": secs, "routine": used.id if used else None,
                   "outcome": outcome, "steps": [s["tool"] for s in res.steps], "answer": res.answer[:160]}  # fmt: skip
            tag = f"routine #{used.id}" if used else "model"
            print(f"{'PASS' if ok else 'FAIL'}  {secs:5.1f}s  {tag:11} {outcome:10} {request}")
            if not ok:
                print(f"      {row['steps']} {row['answer']!r}")
            rows.append(row)
            return row

        try:
            for first, check, variants in TASKS:
                base = await run(first, check)
                for request, vcheck in variants:
                    r = await run(request, vcheck)
                    if r["routine"] and base["seconds"]:
                        print(
                            f"      {base['seconds'] / max(r['seconds'], 0.1):.1f}x the first run's speed"
                        )
        finally:
            await research.shutdown()
            await mcp.close()
            if swap:
                swap.terminate()
    replays = [r for r in rows if r["routine"]]
    firsts = {t[0] for t in TASKS}
    summary = {
        "replayed": f"{len(replays)}/{len(rows) - len(firsts)} variants",
        "replays_ok": f"{sum(r['ok'] for r in replays)}/{len(replays)}",
        "all_ok": f"{sum(r['ok'] for r in rows)}/{len(rows)}",
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "skills.json").write_text(json.dumps({"summary": summary, "runs": rows}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
