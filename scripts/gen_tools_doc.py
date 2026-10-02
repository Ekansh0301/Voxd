"""
Write docs/TOOLS.md from the code: every tool the model can call, grouped by
module, with its permission tier and parameters. Run after adding or changing a tool:

    .venv/bin/python scripts/gen_tools_doc.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tars.agent.tools import Tier  # noqa: E402
from tars.tools import browser, default_registry  # noqa: E402

TIERS = {
    Tier.T0: "T0 read-only, runs at once",
    Tier.T1: "T1 reversible, runs and is logged",
    Tier.T2: "T2 asks you first",
    Tier.T3: "T3 always asks (send, submit, delete…)",
}
GROUPS = {
    "system": "System, timers and notifications", "files": "Files", "shell": "Shell (sandboxed)",
    "desktop": "Desktop, apps, volume, media", "screen": "Reading and operating app windows",
    "vision": "Looking at the screen", "memory": "Memory", "apps": "Your apps",
    "code": "Coding", "music": "Spotube", "keys": "Keyboard and window focus",
    "context": "What's on screen", "research": "Research (hidden browser)",
    "locate": "Clicking by sight", "browser": "Your Firefox (TARS)",
}  # fmt: skip


def main():
    reg = default_registry()
    browser.register(reg, lambda: None)  # the web_* wrappers (normally registered at startup)
    by_group: dict[str, list] = {}
    for tool in reg.tools.values():
        module = tool.handler.__module__.rsplit(".", 1)[-1]
        by_group.setdefault(module, []).append(tool)
    out = [
        "# TARS tools",
        "",
        "Generated from the code by `scripts/gen_tools_doc.py`; don't edit by hand.",
        f"{len(reg.tools)} tools. Tiers decide what happens when the model calls one "
        "(see [SAFETY.md](SAFETY.md)); a tool can also ask for approval itself for a "
        "risky case, such as replacing a file or clicking a Send button.",
        "",
        "| Tier | Meaning |",
        "|---|---|",
        *(f"| {t.name} | {d.split(' ', 1)[1]} |" for t, d in TIERS.items()),
        "",
    ]
    order = [g for g in GROUPS if g in by_group] + sorted(g for g in by_group if g not in GROUPS)
    for group in order:
        out += [
            f"## {GROUPS.get(group, group)}",
            "",
            "| Tool | Tier | What it does | Parameters |",
            "|---|---|---|---|",
        ]
        for t in sorted(by_group[group], key=lambda t: t.name):
            props = t.parameters.get("properties", {})
            required = set(t.parameters.get("required", []))
            params = ", ".join(f"`{p}`" + ("" if p in required else "?") for p in props) or "none"
            desc = t.description.replace("|", "\\|").replace("\n", " ")
            out.append(f"| `{t.name}` | {t.tier.name} | {desc} | {params} |")
        out.append("")
    out.append("`?` = optional parameter.")
    (REPO / "docs" / "TOOLS.md").write_text("\n".join(out) + "\n")
    print(f"wrote docs/TOOLS.md: {len(reg.tools)} tools in {len(order)} groups")


if __name__ == "__main__":
    main()
