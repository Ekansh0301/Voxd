"""
Fast path: unambiguous everyday commands run without the LLM (~0.1 s instead of
~1.5 s). Patterns must match the whole utterance, so anything with more to it
("open YouTube and play lofi") still goes to the agent. Wrong match is worse
than no match: when in doubt, return None.
"""

import re
from dataclasses import dataclass

from tars.sites import SiteRegistry

POLITE = r"(?:(?:hey |ok |okay )?tars,? )?(?:please |kindly |can you |could you |do one thing,? )?"
TAIL = r"(?: for me)?(?: please)?[.!?]*"


@dataclass
class Route:
    tool: str
    args: dict
    ack: str  # spoken right away


def _volume(text: str) -> Route | None:
    if m := re.fullmatch(
        rf"{POLITE}(?:set |change |put )?(?:the )?volume (?:to |at )?(\d{{1,3}})(?: ?%| percent)?{TAIL}",
        text,
    ):
        level = min(100, int(m.group(1)))
        return Route("set_volume", {"level": level}, f"Volume {level} percent.")
    if m := re.fullmatch(rf"{POLITE}(?:turn (?:the )?volume |volume )(up|down)(?: a (?:little )?bit| a little)?{TAIL}", text) or \
            re.fullmatch(rf"{POLITE}(increase|decrease|raise|lower|reduce) (?:the )?volume(?: a (?:little )?bit| a little)?{TAIL}", text):  # fmt: skip
        up = m.group(1) in ("up", "increase", "raise")
        return Route("set_volume", {"change": 10 if up else -10}, "Louder." if up else "Quieter.")
    if m := re.fullmatch(rf"{POLITE}(mute|unmute)(?: the)?(?: sound| audio| volume)?{TAIL}", text):
        mute = m.group(1) == "mute"
        return Route("set_volume", {"mute": mute}, "Muted." if mute else "Unmuted.")
    return None


MEDIA = {
    "pause": "pause", "stop": "pause", "play": "play", "resume": "play", "continue": "play",
    "next": "next", "skip": "next", "previous": "previous", "go back": "previous",
}  # fmt: skip


def _media(text: str) -> Route | None:
    words = "|".join(MEDIA)
    m = re.fullmatch(
        rf"{POLITE}({words})(?: the| this)?(?: song| track| music| video| playback)?(?: track| song)?{TAIL}",
        text,
    ) or re.fullmatch(rf"{POLITE}(next|previous) (?:song|track|video){TAIL}", text)
    if not m:
        return None
    action = MEDIA[m.group(1)]
    return Route("media_control", {"action": action}, {"pause": "Paused.", "play": "Playing.",
                 "next": "Next.", "previous": "Going back."}[action])  # fmt: skip


def _open(text: str, sites: SiteRegistry) -> Route | None:
    m = re.fullmatch(
        rf"{POLITE}(?:open|launch|start|go to|bring up)(?: up)? (?:the )?(.+?)(?: app| website| site)?{TAIL}",
        text,
    )
    if not m or re.search(r"\b(and|then|search|play|with|in|to)\b", m.group(1)):
        return None
    target = m.group(1).strip()
    site = sites.resolve(target)
    if site is not None:
        if site.access == "blocked":
            return None  # let the agent explain the refusal
        return Route("open_url", {"url": site.url}, f"Opening {site.key.capitalize()}.")
    if len(target.split()) <= 3:
        return Route("open_app", {"name": target}, f"Opening {target}.")
    return None


def _youtube(text: str) -> Route | None:
    """'play lofi beats on youtube', 'search youtube for linux tutorials'."""
    if m := re.fullmatch(rf"{POLITE}(?:play|put on) (.+?) on youtube{TAIL}", text):
        q = m.group(1).strip()
        return Route(
            "open_site",
            {"site": "youtube", "action": "play", "query": q},
            f"Playing {q} on YouTube.",
        )
    if m := re.fullmatch(
        rf"{POLITE}(?:search youtube for|search for (.+?) on youtube|look up (.+?) on youtube)(?: (.+?))?{TAIL}",
        text,
    ):
        q = next(g for g in m.groups() if g)
        return Route(
            "open_site",
            {"site": "youtube", "action": "search", "query": q.strip()},
            "Searching YouTube.",
        )
    return None


def match(text: str, sites: SiteRegistry) -> Route | None:
    t = re.sub(r"\s+", " ", text.lower().strip())
    if re.fullmatch(rf"{POLITE}(?:what(?:'s| is) the time|what time is it)(?: now)?{TAIL}", t):
        return Route("get_datetime", {}, "")
    return _volume(t) or _media(t) or _youtube(t) or _open(t, sites)
