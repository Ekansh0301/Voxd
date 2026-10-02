"""
Filling web forms from your profile (~/.config/tars/profile.yaml): match each field's
label to a profile entry, fill the clear matches, and report the rest. Nothing is
submitted: submit buttons always ask first (they're Tier 3), and password, payment and
ID-number fields are never filled.
"""

import difflib
import re

from tars import profile
from tars.agent.tools import Context, Registry, Tier, obj
from tars.tools import browser

FIELD_ROLES = ("input", "textbox", "textarea", "searchbox", "combobox", "spinbutton")
# label words -> profile key
SYNONYMS = {
    "name": ["full name", "your name", "name", "student name", "applicant name"],
    "first_name": ["first name", "given name", "forename"],
    "last_name": ["last name", "surname", "family name"],
    "email": ["email", "e-mail", "email id", "email address", "mail id"],
    "phone": [
        "phone",
        "mobile",
        "mobile number",
        "phone number",
        "contact number",
        "whatsapp number",
    ],
    "roll_number": [
        "roll number",
        "roll no",
        "roll",
        "student id",
        "enrollment number",
        "enrolment no",
    ],
    "college": [
        "college",
        "institute",
        "institution",
        "university",
        "school",
        "organisation",
        "organization",
    ],
    "address": ["address", "street address", "postal address"],
    "city": ["city", "town"],
    "branch": ["branch", "department", "major", "programme", "program"],
    "year": ["year of study", "current year", "batch", "graduation year"],
}
NEVER = re.compile(
    r"pass(word|code)|card|cvv|otp|pin\b|aadhaar|pan\b|ssn|bank|account number|ifsc", re.I
)


def _fields_on_page(snapshot: str) -> list[str]:
    names = []
    for line in snapshot.splitlines()[1:]:
        m = re.match(r'^(\w+) "(.*)"', line.strip())
        if (
            m
            and (m.group(1) in FIELD_ROLES or m.group(1) == "field")
            and not m.group(2).startswith("unnamed ")
        ):
            names.append(m.group(2))
    return list(dict.fromkeys(names))


def match_field(label: str, prof: dict[str, str]) -> str | None:
    """'Email ID *' -> 'email', or None if unsure."""
    clean = re.sub(r"[^a-z ]", " ", label.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean or NEVER.search(label):
        return None
    best, score, best_len = None, 0.0, 0
    for key, words in SYNONYMS.items():
        for w in words:
            s = (
                1.0
                if clean == w
                else (
                    0.9
                    if re.search(rf"\b{re.escape(w)}\b", clean)
                    else difflib.SequenceMatcher(None, clean, w).ratio()
                )
            )
            if (s, len(w)) > (score, best_len):  # ties: the longer, more specific phrase
                best, score, best_len = key, s, len(w)
    if best is None or score < 0.8:
        return None
    if best in ("first_name", "last_name") and best not in prof and "name" in prof:
        return best  # derived from the full name below
    return best if best in prof else None


def _value(key: str, prof: dict[str, str]) -> str:
    if key in prof:
        return prof[key]
    parts = prof.get("name", "").split()
    return (parts[0] if key == "first_name" else " ".join(parts[1:])) if parts else ""


async def fill_form(ctx: Context) -> str:
    prof = profile.load()
    if not prof:
        return ("error: there's no profile to fill from. The user writes their details in "
                "~/.config/tars/profile.yaml (name, email, phone, roll_number, college ...)")  # fmt: skip
    page = await browser.web_read(ctx)
    filled: list[str] = []
    left: list[str] = []
    for label in _fields_on_page(page):
        key = match_field(label, prof)
        value = _value(key, prof) if key else ""
        if not value:
            left.append(label)
            continue
        out = await browser.web_fill(ctx, label, value)
        if out.lstrip().lower().startswith(("error", "refused")):
            left.append(label)
        else:
            filled.append(f"{label}: {value}")
    review = ("filled: " + ("; ".join(filled) or "nothing") + "\nleft for you: " + ("; ".join(left) or "nothing")
              + "\nNothing was submitted. Read the review to the user; submitting asks first.")  # fmt: skip
    return review


def register(reg: Registry):
    reg.tool(
        "fill_form",
        "Fill the form on the current Firefox page from the user's saved profile (name, email, "
        "phone, roll number, college...). Never submits; returns what was filled for review.",
        obj([]),
        tier=Tier.T1,
        speak="Filling the form",
    )(fill_form)
