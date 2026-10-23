"""
Text of a turn as it is spoken, shown and remembered: no markdown in speech, and
the history's action notes (which the model must never write itself).
Kept apart from the voice service so it imports without audio libraries.
"""

import re

# The model sometimes copies the action notes kept in the history into its reply,
# claiming something it never did; such text is never spoken, shown or kept.
FAKE_NOTE = re.compile(
    r"[ \t]*\n?[ \t]*(?:\[(?:done|actions? taken)|\(actions taken for this request)[^\n]*", re.I
)


def _brief(args: dict) -> str:
    """Tool args for the history note, long values cut ('text': 'Dear …')."""
    return ", ".join(f"{k}={str(v)[:120 if k in ('path', 'source', 'destination', 'url') else 40]!r}"
                     for k, v in args.items())  # fmt: skip


def _note(steps: list[tuple[str, dict]]) -> str:
    """What was done for a request, kept on the user's side of the history (in the
    assistant's own replies the model learns to write it instead of doing it)."""
    done = ", ".join(f"{tool}({_brief(args)})" for tool, args in steps)
    return f"\n(actions taken for this request: {done[:240]})" if done else ""


def _plain(text: str) -> str:
    """What's spoken and shown: no markdown emphasis, bullets, backticks or em dashes."""
    text = FAKE_NOTE.sub("", text)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*•]|\d+\.)\s+", "", text)
    return text.replace(" — ", ", ").replace("—", ", ")
