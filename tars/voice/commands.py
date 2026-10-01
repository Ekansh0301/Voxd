"""
Voice commands handled without the LLM: personality settings, as in the film.

    "humor 40%" · "set your honesty to ninety percent" · "verbosity high"
"""

import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tars.config import USER

UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def words_to_number(text: str) -> int | None:
    """'40', 'forty', 'forty five', 'forty-five', 'a hundred' -> int."""
    text = text.strip().lower().replace("-", " ")
    if re.fullmatch(r"\d{1,3}", text):
        return int(text)
    total = 0
    for w in text.split():
        if w in ("a", "one") and "hundred" in text:
            continue
        if w == "hundred":
            total = (total or 1) * 100
        elif w in TENS:
            total += TENS[w]
        elif w in UNITS:
            total += UNITS.index(w)
        else:
            return None
    return total if text else None


NUMBER = r"(\d{1,3}|(?:a |one )?hundred|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
PERCENT_SETTING = re.compile(
    rf"\b(humou?r|honesty)(?: setting)?(?: (?:to|at|is))? {NUMBER}(?: ?%| percent)?\b"
)
VERBOSITY = re.compile(r"\bverbosity(?: setting)?(?: (?:to|at))? (low|medium|high)\b")


def parse(text: str) -> tuple[str, int | str] | None:
    """('humor', 40) / ('honesty', 90) / ('verbosity', 'high') or None."""
    t = text.lower().replace(",", " ")
    t = re.sub(r"\s+", " ", t)
    if m := PERCENT_SETTING.search(t):
        value = words_to_number(m.group(2))
        if value is not None and 0 <= value <= 100:
            return ("humor" if m.group(1).startswith("hum") else "honesty", value)
    if m := VERBOSITY.search(t):
        return ("verbosity", m.group(1))
    return None


def apply(cfg: dict, key: str, value: int | str, user_file: Path = USER) -> str:
    """Update the running config and persist it; returns the spoken confirmation."""
    cfg.setdefault("personality", {})[key] = value
    data = yaml.safe_load(user_file.read_text()) if user_file.exists() else {}
    data = data or {}
    data.setdefault("personality", {})[key] = value
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text(yaml.safe_dump(data, sort_keys=False))
    spoken = f"{value} percent" if isinstance(value, int) else value
    return f"{key.capitalize()} setting {spoken}."
