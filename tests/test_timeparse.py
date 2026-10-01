from datetime import datetime, timezone

import pytest

from tars.timeparse import parse_when

NOW = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)  # a Thursday


@pytest.mark.parametrize(
    "text,expected",
    [
        ("in 30 minutes", datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)),
        ("in 2 hours", datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)),
        ("in an hour", datetime(2026, 10, 1, 11, 30, tzinfo=timezone.utc)),
        ("in half an hour", datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)),
        ("tomorrow at 9", datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)),
        ("tomorrow 9:30 pm", datetime(2026, 10, 2, 21, 30, tzinfo=timezone.utc)),
        ("Tomorrow", datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)),
        ("at 6 pm", datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)),
        ("at 9 am", datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)),  # already past today
        ("today 18:00", datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)),
        ("tonight at 8", datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)),
        ("friday at 10 am", datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)),
        ("next monday 9", datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)),
        (
            "thursday 5 pm",
            datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc),
        ),  # same weekday -> next week
        ("2026-10-03T07:15", datetime(2026, 10, 3, 7, 15, tzinfo=timezone.utc)),
        ("12 pm", datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)),
    ],
)
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["whenever", "at 25", "soonish", ""])
def test_unparseable(text):
    assert parse_when(text, NOW) is None
