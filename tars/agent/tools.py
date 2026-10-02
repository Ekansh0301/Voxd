"""
Tool framework: what the agent can do, at which permission tier.

Tiers (docs/PLAN.md §12.1):
  T0  read-only                         runs automatically
  T1  local and reversible              runs automatically, logged
  T2  local destructive / system change needs your approval
  T3  external or irreversible           needs your approval with a readback
A tool may raise its tier for a particular call (e.g. a shell command that writes).
"""

import enum
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from tars.sites import SiteRegistry

log = logging.getLogger("tars.tools")


class Tier(enum.IntEnum):
    T0 = 0
    T1 = 1
    T2 = 2
    T3 = 3


class Denied(Exception):
    """Policy refused the action outright (no approval can unlock it)."""


@dataclass
class Context:
    """What tools may touch. Evals swap in a throwaway home and a fake desktop."""

    home: Path = field(default_factory=Path.home)
    sites: SiteRegistry = field(default_factory=SiteRegistry)
    # async (summary) -> bool; None means "deny anything that needs approval"
    approve: Callable[[str], Awaitable[bool]] | None = None
    desktop: bool = True  # False: record desktop actions instead of performing them
    actions: list[str] = field(default_factory=list)  # audit log of performed actions
    notify: Callable[[str], None] | None = None  # e.g. timers speaking when they fire

    async def require(self, tier: "Tier", summary: str) -> None:
        """Ask for approval when tier >= T2; raise Denied if refused."""
        if tier < Tier.T2:
            return
        if self.approve is None or not await self.approve(summary):
            raise Denied(f"not approved: {summary}")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    tier: Tier
    handler: Callable[..., Awaitable[str] | str]
    speak: str = ""  # short narration while it runs, e.g. "Checking"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, ctx: Context, args: dict) -> str:
        result = self.handler(ctx, **args)
        if inspect.isawaitable(result):
            result = await result
        return str(result)


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def tool(
        self, name: str, description: str, parameters: dict | None = None,
        tier: Tier = Tier.T0, speak: str = "",
    ):  # fmt: skip

        def wrap(fn):
            self.tools[name] = Tool(
                name, description, parameters or {"type": "object", "properties": {}},
                tier, fn, speak,
            )  # fmt: skip
            return fn

        return wrap

    def schemas(self, names: list[str] | None = None) -> list[dict]:
        return [t.schema() for n, t in self.tools.items() if names is None or n in names]

    async def call(self, ctx: Context, name: str, args: dict) -> str:
        """Run a tool; policy refusals and errors come back as text for the model."""
        tool = self.tools.get(name)
        if tool is None:
            return f"error: no tool named {name!r}"
        if "_raw" in args:
            return f"error: arguments were not valid JSON: {args['_raw'][:200]}"
        try:
            try:  # "bad arguments" only when they really don't fit the tool
                inspect.signature(tool.handler).bind(ctx, **args)
            except TypeError as e:
                return f"error: bad arguments for {name}: {e}"
            await ctx.require(tool.tier, f"{name} {args}")
            out = await tool.run(ctx, args)
            ctx.actions.append(f"{name} {args}")
            return out
        except Denied as e:
            return f"refused: {e}"
        except (ValueError, ConnectionError) as e:  # expected: "nothing named X", app not open
            return f"error: {e}"
        except Exception as e:
            log.exception(f"tool {name} failed")
            return f"error: {type(e).__name__}: {e}"


def obj(required: list[str] | None = None, **props: dict) -> dict:
    """Small helper for JSON-schema parameter objects."""
    return {"type": "object", "properties": props, "required": required or []}
