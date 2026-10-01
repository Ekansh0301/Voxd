"""
Window list and focus through the "TARS windows" GNOME Shell extension
(deploy/gnome-extension, D-Bus org.tars.Windows). Wayland gives apps no other
way to focus another app's window.
"""

import difflib
import json
from dataclasses import dataclass

from jeepney import DBusAddress, new_method_call
from jeepney.io.asyncio import open_dbus_router

WINDOWS = DBusAddress("/org/tars/Windows", "org.tars.Windows", "org.tars.Windows")


class NoExtension(Exception):
    pass


@dataclass
class Window:
    id: int
    title: str
    app: str  # desktop file id, e.g. "spotube.desktop"
    wm_class: str
    pid: int
    focused: bool
    minimized: bool
    x: int
    y: int
    width: int
    height: int
    workspace: int

    @property
    def label(self) -> str:
        app = self.app.removesuffix(".desktop") or self.wm_class
        return f"{app}: {self.title}" if self.title else app


async def _call(method: str, sig: str | None = None, body: tuple = ()):
    async with open_dbus_router(bus="SESSION") as router:
        msg = (
            new_method_call(WINDOWS, method, sig, body) if sig else new_method_call(WINDOWS, method)
        )
        reply = await router.send_and_get_reply(msg)
    if reply.header.message_type.name == "error":
        raise NoExtension(
            "the TARS windows GNOME extension isn't running "
            "(scripts/install_gnome_extension.sh, then log out and back in)"
        )
    return reply.body


async def list_windows() -> list[Window]:
    (raw,) = await _call("List")
    return [Window(**w) for w in json.loads(raw)]


async def activate(win: Window) -> bool:
    (ok,) = await _call("Activate", "t", (win.id,))
    return bool(ok)


def find(query: str, wins: list[Window]) -> Window | None:
    """Best window for 'spotube', 'super productivity', 'firefox outlook', ..."""
    q = query.lower().strip()
    squash = q.replace(" ", "")

    def keys(w: Window) -> str:
        return f"{w.app} {w.wm_class} {w.title}".lower()

    exact = [w for w in wins if q in keys(w) or squash in keys(w).replace(" ", "")]
    if exact:  # prefer the app-name match over a title mention, then the focused one
        exact.sort(
            key=lambda w: (
                squash not in (w.app + w.wm_class).lower().replace(" ", ""),
                not w.focused,
            )
        )
        return exact[0]
    names = {w.label.lower(): w for w in wins}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.5)
    return names[close[0]] if close else None
