"""A turn that uses and learns routines: match -> replay the steps -> learn from the outcome.
Shared by the voice service and the evals, so both behave the same."""

import logging

from tars.agent.loop import TurnResult, run_turn
from tars.agent.tools import Context, Registry
from tars.skills.store import Skill, Skills

log = logging.getLogger("tars.skills")


async def turn_with_skills(skills: Skills | None, request: str, messages: list[dict], registry: Registry,
                           ctx: Context, endpoint: str, model: str, **kw) -> tuple[TurnResult, Skill | None, str]:  # fmt: skip
    """Returns (result, the routine used if any, 'learned'/'reinforced'/'failed'/'')."""
    skill = skills.match(request) if skills else None
    if skill:
        log.info(f"using routine #{skill.id} {skill.slots}")
    result = await run_turn(
        messages, registry, ctx, endpoint, model, plan=skill.plan() if skill else None, **kw
    )
    outcome = skills.learn(request, result.steps, result.answer, used=skill) if skills else ""
    if outcome:
        log.info(f"routine {outcome}")
    return result, skill, outcome
