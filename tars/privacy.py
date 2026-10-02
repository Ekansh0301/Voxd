"""Keep personal details out of text TARS sends off the laptop (web AIs, later cloud
models): swap them for placeholders, and swap the placeholders back in the answer."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\d(?!\w)")
LONG_NUMBER = re.compile(r"(?<!\w)\d{7,}(?!\w)")


def redact(text: str, profile: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """'Mail ravi@x.in about roll 2021101' -> ('Mail [EMAIL1] about roll [NUMBER1]', mapping)."""
    mapping: dict[str, str] = {}
    out = text
    for key, value in sorted((profile or {}).items(), key=lambda kv: -len(kv[1])):
        if len(value) >= 3 and re.search(re.escape(value), out, re.I):
            tag = f"[{key.upper()}]"
            mapping[tag] = value
            out = re.sub(re.escape(value), tag, out, flags=re.I)
    for pattern, label in ((EMAIL, "EMAIL"), (PHONE, "PHONE"), (LONG_NUMBER, "NUMBER")):
        for i, found in enumerate(dict.fromkeys(pattern.findall(out)), 1):
            tag = f"[{label}{i}]"
            mapping[tag] = found
            out = out.replace(found, tag)
    return out, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for tag, value in mapping.items():
        text = text.replace(tag, value)
    return text
