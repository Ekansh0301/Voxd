"""Remember and recall facts across sessions."""

from tars.agent.tools import Context, Registry, Tier, obj
from tars.memory.store import Memory


def register(reg: Registry, memory: Memory):
    def remember(ctx: Context, fact: str) -> str:
        fid = memory.remember(fact)
        return f"remembered (fact {fid}): {fact}"

    def recall(ctx: Context, query: str) -> str:
        facts = memory.facts(query, limit=6)
        turns = memory.turns(query, limit=3)
        out = [f"fact {i}: {t}" for i, t in facts]
        out += [f"[{when}] you: {u} | TARS: {a[:160]}" for when, u, a in turns]
        return "\n".join(out) or f"nothing remembered about {query!r}"

    def forget(ctx: Context, fact_id: int) -> str:
        return f"forgot fact {fact_id}" if memory.forget(fact_id) else f"no fact {fact_id}"

    reg.tool("remember", "Save a fact about the user or their preferences for future sessions.",
             obj(["fact"], fact={"type": "string"}), tier=Tier.T1)(remember)  # fmt: skip
    reg.tool("recall", "Search remembered facts and past conversations.",
             obj(["query"], query={"type": "string"}))(recall)  # fmt: skip
    reg.tool("forget", "Delete a remembered fact by its number.", obj(["fact_id"], fact_id={"type": "integer"}),
             tier=Tier.T1)(forget)  # fmt: skip
