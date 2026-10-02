"""Desktop actions: open sites and apps, volume, media playback, notifications."""

import configparser
import difflib
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from tars.agent.tools import Context, Denied, Registry, Tier, obj

APP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/snapd/desktop/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
]
ALIASES = {"vs code": "code", "vscode": "code", "terminal": "terminal", "files": "files",
           "file manager": "files", "browser": "firefox", "calculator": "calculator",
           "settings": "settings", "text editor": "text editor"}  # fmt: skip


def _run(ctx: Context, argv: list[str], what: str) -> None:
    ctx.actions.append(what)
    if ctx.desktop:
        subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )


# (is_connected, async open) set by tars.tools.browser when Firefox (TARS) is available
BROWSER: tuple[Callable[[], bool], Callable[[str], Awaitable[str]]] | None = None


async def open_url(ctx: Context, url: str) -> str:
    if not re.match(r"^(https?|file|data|about):", url):
        site = ctx.sites.resolve(url)  # "youtube" -> registry entry
        url = site.url if site else "https://" + url
    decision = ctx.sites.check(url, "open")
    if not decision.allowed:
        raise Denied(decision.reason)
    if ctx.desktop and BROWSER and BROWSER[0]():
        ctx.actions.append(f"open {url} (Firefox TARS)")
        await BROWSER[1](url)  # starts Firefox (TARS) if needed
        return f"opened {url} in Firefox (TARS); web_read can read it"
    _run(ctx, ["xdg-open", url], f"open {url}")
    if ctx.desktop and BROWSER:
        return (f"opened {url} in the user's normal Firefox. TARS can't read or type there; "
                "to do more, ask the user to close Firefox, then open the page again.")  # fmt: skip
    return f"opened {url}"


def _apps() -> dict[str, tuple[str, str]]:
    """Visible .desktop apps: lowercase name -> (desktop id, display name)."""
    found: dict[str, tuple[str, str]] = {}
    for d in APP_DIRS:
        for f in d.glob("*.desktop") if d.is_dir() else []:
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Type") != "Application":
                continue
            name = e.get("Name", f.stem)
            for key in {name.lower(), f.stem.lower(), f.stem.split(".")[-1].lower(),
                        *(k.strip().lower() for k in e.get("Keywords", "").split(";") if k.strip())}:  # fmt: skip
                found.setdefault(key, (f.stem, name))
    return found


async def _wait_for_window(names: list[str], timeout: float = 20) -> str:
    """Wait until the app's window is up, so the next read_screen sees its contents."""
    import asyncio

    from tars.perception.windows import NoExtension, find, list_windows

    try:
        before = {w.id for w in await list_windows()}
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            wins = await list_windows()
            for n in names:
                w = find(n, wins)
                if w and n in f"{w.app}{w.wm_class}{w.title}".lower().replace(
                    " ", ""
                ):  # a real match
                    if w.id not in before:
                        await asyncio.sleep(2.5)  # just appeared: let it draw its contents
                    return " (its window is up)"
            await asyncio.sleep(0.5)
        return " (its window hasn't appeared yet; check with read_screen in a moment)"
    except NoExtension:
        await asyncio.sleep(3)
        return ""


async def open_app(ctx: Context, name: str) -> str:
    from tars.tools.apps import AppRegistry, launch

    registered = AppRegistry().resolve(name)  # config/apps.yaml: right flags, access rules
    if registered is not None:
        out = launch(ctx, registered)
        if ctx.desktop:
            names = [registered.key, *registered.aliases, Path(registered.launch[0]).name]
            out += await _wait_for_window([n.replace(" ", "").lower() for n in names])
        return out
    apps = _apps()
    q = ALIASES.get(name.lower().strip(), name.lower().strip())
    close = difflib.get_close_matches(q, list(apps), n=1, cutoff=0.6)
    key = q if q in apps else (close[0] if close else None)
    if key is None:
        return f"error: no installed app matches {name!r}"
    desktop_id, display = apps[key]
    _run(ctx, ["gtk-launch", desktop_id], f"launch {desktop_id}")
    if ctx.desktop:
        return f"opened {display}" + await _wait_for_window(
            [display.lower(), desktop_id.split(".")[-1].lower()]
        )
    return f"opened {display}"


def _wpctl(*args: str) -> str:
    r = subprocess.run(["wpctl", *args], capture_output=True, text=True, timeout=5)
    return r.stdout.strip()


def set_volume(ctx: Context, level: int | None = None, change: int | None = None,
               mute: bool | None = None) -> str:  # fmt: skip
    if not shutil.which("wpctl"):
        return "error: wpctl not available"
    sink = "@DEFAULT_AUDIO_SINK@"
    if mute is not None:
        ctx.actions.append(f"mute {mute}")
        if ctx.desktop:
            _wpctl("set-mute", sink, "1" if mute else "0")
    if level is not None:
        ctx.actions.append(f"volume {level}%")
        if ctx.desktop:
            _wpctl("set-volume", "-l", "1.0", sink, f"{max(0, min(100, level)) / 100:.2f}")
    elif change is not None:
        ctx.actions.append(f"volume {change:+d}%")
        if ctx.desktop:
            _wpctl("set-volume", "-l", "1.0", sink, f"{abs(change)}%{'+' if change > 0 else '-'}")
    now = _wpctl("get-volume", sink) if ctx.desktop else "Volume: (dry run)"
    m = re.search(r"([\d.]+)", now)
    state = f"{float(m.group(1)) * 100:.0f}%" if m else now
    return f"volume now {state}{' (muted)' if 'MUTED' in now else ''}"


def media_control(ctx: Context, action: str) -> str:
    """MPRIS over D-Bus (Firefox/YouTube, Spotify, VLC... all expose it)."""
    method = {"play": "Play", "pause": "Pause", "toggle": "PlayPause", "next": "Next",
              "previous": "Previous", "stop": "Stop"}.get(action)  # fmt: skip
    if not method:
        return f"error: unknown action {action!r}"
    ctx.actions.append(f"media {action}")
    if not ctx.desktop:
        return f"media {action} (dry run)"
    names = subprocess.run(["busctl", "--user", "list", "--no-legend"], capture_output=True,
                           text=True, timeout=5).stdout  # fmt: skip
    players = [
        line.split()[0] for line in names.splitlines() if line.startswith("org.mpris.MediaPlayer2.")
    ]
    if not players:
        return "nothing is playing media right now"
    for p in players:
        subprocess.run(["busctl", "--user", "call", p, "/org/mpris/MediaPlayer2",
                        "org.mpris.MediaPlayer2.Player", method], capture_output=True, timeout=5)  # fmt: skip
    return f"sent {action} to {', '.join(p.split('.')[3] for p in players)}"


def notify(ctx: Context, message: str) -> str:
    _run(ctx, ["notify-send", "-a", "TARS", "TARS", message], f"notify {message}")
    return "notification shown"


def register(reg: Registry):
    reg.tool("open_url", "Open a website in Firefox: a URL or a known site name (outlook, youtube, github...). "
             "To search or play something on the user's sites, use open_site instead.",
             obj(["url"], url={"type": "string"}), tier=Tier.T1, speak="Opening")(open_url)  # fmt: skip
    reg.tool("open_app", "Launch an installed desktop application by name.",
             obj(["name"], name={"type": "string"}), tier=Tier.T1, speak="Opening")(open_app)  # fmt: skip
    reg.tool(
        "set_volume", "Set the volume (level 0-100), change it (e.g. +10 / -10), or mute/unmute.",
        obj([], level={"type": "integer", "minimum": 0, "maximum": 100},
            change={"type": "integer"}, mute={"type": "boolean"}), tier=Tier.T1,
    )(set_volume)  # fmt: skip
    reg.tool("media_control", "Control music/video playback in any player.",
             obj(["action"], action={"type": "string", "enum": ["play", "pause", "toggle", "next", "previous", "stop"]}),
             tier=Tier.T1)(media_control)  # fmt: skip
    reg.tool("notify", "Show a desktop notification.", obj(["message"], message={"type": "string"}),
             tier=Tier.T1)(notify)  # fmt: skip
