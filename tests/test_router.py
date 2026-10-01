import pytest

from tars.router import match
from tars.sites import SiteRegistry

SITES = SiteRegistry()


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("Open YouTube.", "open_url", {"url": "https://www.youtube.com/"}),
        ("TARS, open Outlook please", "open_url", {"url": "https://outlook.office365.com/mail/"}),
        ("open outluk", "open_url", {"url": "https://outlook.office365.com/mail/"}),
        ("Open the calculator app", "open_app", {"name": "calculator"}),
        ("launch vs code", "open_app", {"name": "vs code"}),
        ("Set the volume to 30%", "set_volume", {"level": 30}),
        ("volume 70 percent", "set_volume", {"level": 70}),
        ("Increase the volume a little bit", "set_volume", {"change": 10}),
        ("turn volume down", "set_volume", {"change": -10}),
        ("Mute", "set_volume", {"mute": True}),
        ("Pause the song.", "media_control", {"action": "pause"}),
        ("do one thing, play the next track", None, None),  # ambiguous phrasing: agent
        ("Next song", "media_control", {"action": "next"}),
        ("resume the music", "media_control", {"action": "play"}),
        ("What's the time?", "get_datetime", {}),
        ("what time is it now", "get_datetime", {}),
    ],
)
def test_routes(text, tool, args):
    r = match(text, SITES)
    if tool is None:
        assert r is None or r.tool == "media_control"
    else:
        assert r is not None and r.tool == tool and r.args == args


@pytest.mark.parametrize(
    "text",
    [
        "Open YouTube and play some lofi music",
        "open the report in Documents",
        "open moodle",  # blocked: the agent explains
        "what is the time zone of Japan",
        "can you play something relaxing",
        "set a timer for ten minutes",
        "open the file I downloaded yesterday from my college portal",
        "how do I increase the volume of my voice",
    ],
)
def test_leaves_anything_more_to_the_agent(text):
    assert match(text, SITES) is None
