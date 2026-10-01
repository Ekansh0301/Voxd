"""
Parse the times people say for reminders, so the 4B model never does date math:
"in 30 minutes", "in 2 hours", "tomorrow at 9", "tomorrow 9:30 pm", "at 6 pm",
"today 18:00", "friday at 10 am", or an ISO time like "2026-10-02T09:00".
"""

import re
from datetime import datetime, timedelta

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now().astimezone()
    t = text.strip().lower().replace(".", "")
    try:
        dt = datetime.fromisoformat(text.strip())
        return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
    except ValueError:
        pass
    if m := re.fullmatch(r"in (\d+|an?|half an?) ?(minute|min|hour|hr|day)s?", t):
        count, unit = m.group(1), m.group(2)[0]  # unit: m / h / d
        amount = 0.5 if count.startswith("half") else 1.0 if count in ("a", "an") else float(count)
        return (
            now
            + {
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
            }[unit]
        )
    day_offset = 0
    rest = t
    if m := re.match(
        r"(today|tonight|tomorrow|day after tomorrow|(?:next )?(?:"
        + "|".join(DAYS)
        + r"))\b\s*(?:at )?",
        t,
    ):
        word = m.group(1).replace("next ", "")
        rest = t[m.end() :]
        if word == "tomorrow":
            day_offset = 1
        elif word == "day after tomorrow":
            day_offset = 2
        elif word in DAYS:
            day_offset = (DAYS.index(word) - now.weekday()) % 7 or 7
    rest = re.sub(r"^at ", "", rest).strip()
    if not rest:  # "tomorrow" alone -> 9 am
        if day_offset == 0 and t not in ("tonight",):
            return None
        hour, minute = (20, 0) if t == "tonight" else (9, 0)
    else:
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))? ?(am|pm)?", rest)
        if not m:
            return None
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif ampm is None and t.startswith("tonight") and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            return None
    target = (now + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if day_offset == 0 and target <= now:  # "at 9" when it's already 10 -> tomorrow
        target += timedelta(days=1)
    return target
