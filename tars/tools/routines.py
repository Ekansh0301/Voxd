"""Routines: ones TARS learned from finished tasks, and ones the user teaches by name."""

from tars.agent.tools import Context, Registry, Tier, obj
from tars.skills.store import Skills


def register(reg: Registry, skills: Skills):
    def create_routine(ctx: Context, name: str, steps: list[str]) -> str:
        steps = [str(s).strip() for s in steps if str(s).strip()][:12]
        if not name.strip() or not steps:
            return "error: a routine needs a name and at least one step"
        skills.add_routine(name, steps)
        return f"saved routine {name!r}: " + "; ".join(steps) + f". Say {name!r} to run it."

    def list_routines(ctx: Context) -> str:
        taught = [f"{n}: " + "; ".join(st) for n, st in skills.routines()]
        learned = skills.describe()
        return ("routines you taught:\n" + ("\n".join(taught) or "none") + "\n\nlearned from tasks:\n"
                + ("\n".join(learned) or "none yet"))  # fmt: skip

    def forget_routine(ctx: Context, name: str) -> str:
        if name.strip().lstrip("#").isdigit():
            return (
                "forgot it"
                if skills.forget(int(name.strip().lstrip("#")))
                else f"no learned routine {name}"
            )
        return "forgot it" if skills.forget_routine(name) else f"no routine named {name!r}"

    reg.tool("create_routine", "Save a named routine the user describes: a list of requests run in order "
             "when they say its name (e.g. 'study mode': open my project in VS Code; play my phonk playlist).",
             obj(["name", "steps"], name={"type": "string"},
                 steps={"type": "array", "items": {"type": "string"}}), tier=Tier.T1)(create_routine)  # fmt: skip
    reg.tool(
        "list_routines", "The user's named routines and the ones TARS learned from finished tasks."
    )(list_routines)
    reg.tool("forget_routine", "Delete a named routine, or a learned one by its #number.",
             obj(["name"], name={"type": "string"}), tier=Tier.T1)(forget_routine)  # fmt: skip
