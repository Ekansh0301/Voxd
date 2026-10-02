"""
Learned routines ("skills"): procedural memory, the biggest win for a small model.

After a multi-step task succeeds, its tool calls are saved with the parts that came
from the user's words turned into slots:

    "ask chatgpt what the gate exam is"
      -> trigger  ask {url} what {text}           (slots match words of the request)
      -> steps    open_url(url={url}), web_read(), web_fill(name="Chat with ChatGPT", text={text}), ...

Next time a request fits a trigger, the steps are run directly (no model output per
step) and the model only writes the answer, or carries on if a step failed.

Saved only when it's safe to replay: every free-text argument either came from the
request word for word, or appeared in an earlier step's output (an element name).
A paraphrased argument would replay the old wording, so such tasks aren't saved.

Also user-taught routines: a name and a list of requests ("study mode": open my
project in VS Code; play my phonk playlist; set volume to 30).
"""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from tars import TARS_HOME

SCHEMA = """
create table if not exists skills (
  id integer primary key, signature text unique, triggers text, steps text,
  uses integer default 0, wins integer default 0, fails integer default 0,
  created real, last_used real);
create table if not exists routines (name text primary key, steps text, created real);
"""
POLITE = {
    "please",
    "could",
    "can",
    "would",
    "will",
    "you",
    "hey",
    "tars",
    "ok",
    "okay",
    "kindly",
    "just",
}
# words that are part of how something is asked, never the slot
FIXED = {"a", "an", "the", "my", "me", "to", "in", "on", "of", "for", "and", "is", "what", "how",
         "open", "play", "ask", "tell", "find", "show", "set", "search", "look", "up", "go", "it",
         "this", "that", "from", "with", "at", "by", "about", "some", "your", "i", "be", "do"}  # fmt: skip
NEVER_LEARN = {"edit_file", "write_file", "undo_edit", "remember", "forget", "create_routine",
               "forget_routine", "list_routines", "click_on_screen", "web_switch", "recall"}  # fmt: skip
ENUMS = {"text", "elements", "enter", "left", "right", "true", "false"}
FAILURE = re.compile(
    r"\b(couldn'?t|can'?t|cannot|unable|failed|sorry|not able|didn'?t work|error)\b", re.I
)
MIN_STEPS = 2
DISABLE_AFTER = 2  # replay failures before a skill is retired


def tokens(text: str) -> list[str]:
    """Words of a request, case kept, polite padding and the time stamp dropped."""
    text = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())  # "[Thu 01 Oct 2026, 10:42 AM] ..."
    words = [w.rstrip(".") for w in re.findall(r"[^\s,!?;:\"“”]+", text)]
    words = [w for w in words if w]
    while words and words[0].lower() in POLITE:
        words = words[1:]
    while words and words[-1].lower() in POLITE:
        words = words[:-1]
    return words


@dataclass
class Skill:
    id: int
    triggers: list[list[str]]  # token templates; "{name}" marks a slot
    steps: list[dict]  # {"tool": ..., "args": {...}} with "{name}" inside strings
    uses: int = 0
    wins: int = 0
    fails: int = 0
    slots: dict = field(default_factory=dict)  # filled in by match()

    def plan(self) -> list[dict]:
        """The steps with this request's slot values filled in."""

        def fill(v):
            if isinstance(v, str):
                for k, val in self.slots.items():
                    v = v.replace("{" + k + "}", val)
            return v

        return [
            {"tool": s["tool"], "args": {k: fill(v) for k, v in s["args"].items()}}
            for s in self.steps
        ]


def _match_template(tpl: list[str], words: list[str]) -> dict | None:
    """Literal tokens must match (case-insensitively); each slot takes 1+ words."""
    low = [w.lower() for w in words]

    def go(i: int, j: int) -> dict | None:
        if i == len(tpl):
            return {} if j == len(words) else None
        t = tpl[i]
        if t.startswith("{") and t.endswith("}"):
            for end in range(j + 1, len(words) + 1):
                rest = go(i + 1, end)
                if rest is not None:
                    return {t[1:-1]: " ".join(words[j:end]), **rest}
            return None
        if j < len(words) and low[j] == t.lower():
            return go(i + 1, j + 1)
        return None

    return go(0, 0)


def _span_in(low: list[str], value: str) -> tuple[int, int] | None:
    """The longest run of request words found (as whole words) inside `value`."""
    vlow = value.lower()
    best = None
    for i in range(len(low)):
        for j in range(i + 1, len(low) + 1):
            if best and j - i <= best[1] - best[0]:
                continue
            span = " ".join(low[i:j])
            if len(span) < 3 or all(w in FIXED for w in low[i:j]):
                continue
            if re.search(rf"(?<![\w]){re.escape(span)}(?![\w])", vlow):
                best = (i, j)
    return best


def _uses_request_words(low: list[str], value: str) -> bool:
    """Does `value` contain a meaningful word or number from the request?"""
    vlow = value.lower()
    return any(
        (w.isdigit() or (len(w) >= 3 and w not in FIXED))
        and re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", vlow) is not None
        for w in low
    )


def generalize(request: str, steps: list[dict]) -> tuple[list[str], list[dict]] | None:
    """(trigger template, step templates), or None if the task isn't safe to replay."""
    words = tokens(request)
    low = [w.lower() for w in words]
    template: list[str] = list(words)
    slots: dict[str, tuple[int, int]] = {}  # slot name -> word span in the request
    out_steps = []
    for n, step in enumerate(steps):
        if step["tool"] in NEVER_LEARN:
            return None
        earlier = " ".join(str(s.get("result", "")) for s in steps[:n]).lower()
        args = {}
        for key, value in step["args"].items():
            if not isinstance(value, str) or not value.strip():
                args[key] = value
                continue
            if len(value.split()) >= 2 and value.lower() in earlier:
                args[key] = value  # read off the screen/page in an earlier step: a constant
                continue
            span = _span_in(low, value)
            if span is None:
                if len(value.split()) >= 3 and value.lower() not in earlier:
                    return None  # free text the model wrote (maybe paraphrased): don't replay
                if _uses_request_words(low, value):
                    return (
                        None  # derived from the request ("12 times 7" -> "12*7"): can't refill it
                    )
                args[key] = (
                    value  # a constant: an option, an element name seen earlier, a short value
                )
                continue
            said = " ".join(words[span[0] : span[1]])
            if len(value.split()) >= 3 and len(said) < 0.6 * len(value.strip(" ?.!")):
                return (
                    None  # a few of the user's words inside the model's own sentence: paraphrased
                )
            name = next((nm for nm, sp in slots.items() if sp == span), None)
            if name is None:
                if any(t == "" or t.startswith("{") for t in template[span[0] : span[1]]):
                    return None  # overlaps another slot
                name = key if key not in slots else f"{key}{len(slots) + 1}"
                slots[name] = span
                template[span[0]] = "{" + name + "}"
                for k in range(span[0] + 1, span[1]):
                    template[k] = ""
            at = value.lower().find(said.lower())
            rest = value[:at] + " " + value[at + len(said) :]
            if _uses_request_words(low[: span[0]] + low[span[1] :], rest):
                return None  # more of the request is mixed in than the slot covers
            args[key] = value[:at] + "{" + name + "}" + value[at + len(said) :]
        out_steps.append({"tool": step["tool"], "args": args})
    return [t for t in template if t != ""], out_steps


class Skills:
    def __init__(self, path: Path = TARS_HOME / "skills.db"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    # ── learned skills ──────────────────────────────────────────────────────
    def _rows(self) -> list[Skill]:
        rows = self.db.execute(
            "select id, triggers, steps, uses, wins, fails from skills"
        ).fetchall()
        return [Skill(r[0], json.loads(r[1]), json.loads(r[2]), r[3], r[4], r[5]) for r in rows]

    def match(self, request: str) -> Skill | None:
        words = tokens(request)
        best = None
        for sk in self._rows():
            if sk.fails >= DISABLE_AFTER and sk.fails > sk.wins:
                continue
            for tpl in sk.triggers:
                slots = _match_template(tpl, words)
                if slots is not None and (best is None or sk.wins > best.wins):
                    sk.slots = slots
                    best = sk
        return best

    def learn(self, request: str, steps: list[dict], answer: str, used: Skill | None = None) -> str:
        """Record how a turn went. Returns 'learned', 'reinforced', 'failed' or ''."""
        ok = (
            len(steps) >= MIN_STEPS
            and not any(str(s.get("result", "")).startswith(("error", "refused")) for s in steps)
            and not FAILURE.search(answer or "")
        )
        if used is not None:
            col = "wins" if ok else "fails"
            self.db.execute(f"update skills set uses = uses + 1, {col} = {col} + 1, last_used = ? where id = ?",
                            (time.time(), used.id))  # fmt: skip
            self.db.commit()
            if not ok:
                return "failed"
        if not ok:
            return ""
        gen = generalize(request, steps)
        if gen is None:
            return ""
        trigger, tsteps = gen
        signature = json.dumps(tsteps, sort_keys=True)
        row = self.db.execute(
            "select id, triggers from skills where signature = ?", (signature,)
        ).fetchone()
        if row:
            triggers = json.loads(row[1])
            if trigger not in triggers:
                triggers.append(trigger)
                self.db.execute(
                    "update skills set triggers = ? where id = ?", (json.dumps(triggers), row[0])
                )
                self.db.commit()
            return "reinforced" if used is None else ""
        self.db.execute(
            "insert into skills(signature, triggers, steps, wins, created, last_used) values (?, ?, ?, 1, ?, ?)",
            (signature, json.dumps([trigger]), json.dumps(tsteps), time.time(), time.time()),
        )
        self.db.commit()
        return "learned"

    def describe(self) -> list[str]:
        out = []
        for sk in self._rows():
            tools = ", ".join(s["tool"] for s in sk.steps)
            said = " / ".join(" ".join(t) for t in sk.triggers[:2])
            out.append(
                f'#{sk.id} "{said}" -> {tools} (used {sk.uses}x, {sk.wins} ok, {sk.fails} failed)'
            )
        return out

    def forget(self, skill_id: int) -> bool:
        cur = self.db.execute("delete from skills where id = ?", (skill_id,))
        self.db.commit()
        return cur.rowcount > 0

    # ── routines taught by the user ─────────────────────────────────────────
    def add_routine(self, name: str, steps: list[str]) -> None:
        self.db.execute("insert or replace into routines(name, steps, created) values (?, ?, ?)",
                        (name.lower().strip(), json.dumps(steps), time.time()))  # fmt: skip
        self.db.commit()

    def routine_for(self, request: str) -> tuple[str, list[str]] | None:
        """'study mode', 'run study mode', 'start my study mode routine' -> its steps."""
        words = [w.lower() for w in tokens(request)]
        words = [w for w in words if w not in ("run", "start", "do", "my", "the", "routine")]
        said = " ".join(words)
        for name, steps in self.db.execute("select name, steps from routines"):
            if said == name:
                return name, json.loads(steps)
        return None

    def routines(self) -> list[tuple[str, list[str]]]:
        return [
            (n, json.loads(s))
            for n, s in self.db.execute("select name, steps from routines order by name")
        ]

    def forget_routine(self, name: str) -> bool:
        cur = self.db.execute("delete from routines where name = ?", (name.lower().strip(),))
        self.db.commit()
        return cur.rowcount > 0
