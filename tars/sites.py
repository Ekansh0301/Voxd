"""
Site registry and access policy (config/sites.yaml).

Every browser action goes through `SiteRegistry.check(url, action)` so that,
for example, college sites are never opened or read and typing-practice sites
are only ever opened.
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"

LEVELS = {"blocked": 0, "open_only": 1, "navigate": 2, "full": 3}
# Minimum access level each browser action needs.
ACTION_LEVEL = {
    "open": "open_only",
    "focus": "open_only",
    "read": "navigate",
    "navigate": "navigate",
    "click": "navigate",
    "scroll": "navigate",
    "type": "full",
    "fill": "full",
    "submit": "full",
}


@dataclass
class Site:
    key: str
    url: str
    access: str
    match: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    category: str = ""
    purpose: str = ""
    web_ai: bool = False
    limits: dict = field(default_factory=dict)
    shortcuts: dict = field(default_factory=dict)  # action -> URL template with {q}
    notes: str = ""


@dataclass
class Decision:
    allowed: bool
    reason: str
    site: Optional[Site] = None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _phon(text: str) -> str:
    """Rough sound-alike key so STT spellings match: outluk ~ outlook, gitt hub ~ github."""
    s = _norm(text).replace(" ", "")
    for a, b in (("ph", "f"), ("ck", "k"), ("oo", "u"), ("ee", "i"), ("ou", "u"), ("z", "s")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def _host_path(url: str) -> tuple[str, str]:
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return host.removeprefix("www."), p.path or "/"


class SiteRegistry:
    def __init__(self, path: Path = CONFIG):
        data = yaml.safe_load(path.read_text())
        self.default_access: str = data.get("default_access", "navigate")
        self.sites: dict[str, Site] = {}
        for key, d in data["sites"].items():
            site = Site(key=key, **d)
            if site.access not in LEVELS:
                raise ValueError(f"{key}: unknown access '{site.access}'")
            if not site.match:
                site.match = [_host_path(site.url)[0]]
            self.sites[key] = site

    def site_for_url(self, url: str) -> Optional[Site]:
        """Most specific rule wins: longest matching host(+path prefix)."""
        host, path = _host_path(url)
        best: tuple[int, Optional[Site]] = (-1, None)
        for site in self.sites.values():
            for rule in site.match:
                r_host, _, r_path = rule.lower().removeprefix("www.").partition("/")
                if host != r_host and not host.endswith("." + r_host):
                    continue
                if r_path and not path.lstrip("/").startswith(r_path):
                    continue
                if len(rule) > best[0]:
                    best = (len(rule), site)
        return best[1]

    def check(self, url: str, action: str) -> Decision:
        need = ACTION_LEVEL.get(action)
        if need is None:
            raise ValueError(f"unknown browser action '{action}'")
        site = self.site_for_url(url)
        access = site.access if site else self.default_access
        name = site.key if site else _host_path(url)[0]
        if LEVELS[access] >= LEVELS[need]:
            return Decision(True, f"{name}: {action} allowed ({access})", site)
        if access == "blocked":
            return Decision(False, f"{name} is blocked: TARS never accesses it", site)
        return Decision(False, f"{name} allows only '{access}', not '{action}'", site)

    def resolve(self, spoken: str, cutoff: float = 0.8) -> Optional[Site]:
        """Map a spoken name ("outluk", "cheat sheet") to a site, tolerating STT slips."""
        q = _norm(spoken)
        names, sounds = {}, {}
        for site in self.sites.values():
            for a in [site.key, *site.aliases]:
                names[_norm(a)] = site
                sounds[_phon(a)] = site
        if q in names:
            return names[q]
        if _phon(q) in sounds:
            return sounds[_phon(q)]
        close = difflib.get_close_matches(q, list(names), n=1, cutoff=cutoff)
        return names[close[0]] if close else None

    def hotwords(self) -> list[str]:
        return sorted({a for s in self.sites.values() for a in s.aliases if " " not in a})
