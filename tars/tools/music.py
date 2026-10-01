"""
Spotube: "play Zinda", "play Believer", "play death bed by Powfu", "play some music".

Spotube is a Flutter app and exposes no accessibility tree. So:
  - songs in your own library (saved queue = liked songs, plus history, read
    read-only from Spotube's database) play through Spotube Connect, its local
    WebSocket remote, when that is switched on in Spotube's settings;
  - anything else (or with Connect off) is played the way you would: focus
    Spotube, Search, type, right-click the top result, "Play next", Next. The
    clicks land on fixed spots of Spotube's layout (window position from the
    GNOME extension); "Play next" keeps your queue, unlike clicking a result,
    which asks to clear it. MPRIS then confirms what is playing;
  - no particular song ("play some music") resumes over MPRIS.
Only two settings columns are read from the database; never the credentials
stored next to them.
"""

import asyncio
import contextlib
import difflib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import websockets

from tars.agent.tools import Context, Registry, Tier, obj
from tars.perception.keyboard import InputError, Keyboard
from tars.perception.screenshot import take_screenshot
from tars.perception.windows import NoExtension, Window, activate, list_windows
from tars.perception.windows import find as find_window

DB = Path.home() / ".local/share/spotube/db.sqlite"
DEFAULT_PORT = 9150
ANY_SONG = {"", "music", "some music", "a song", "some song", "something", "songs", "anything"}


def _db() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)


def library() -> tuple[list[dict], list[dict]]:
    """(saved queue, history tracks), as Spotube's own track JSON."""
    if not DB.exists():
        return [], []
    with _db() as c:
        row = c.execute("select tracks from audio_player_state_table limit 1").fetchone()
        queue = json.loads(row[0]) if row and row[0] else []
        hist = [json.loads(d) for (d,) in c.execute(
            "select data from history_table where type = 'track' order by created_at desc")]  # fmt: skip
    return queue, hist


def connect_settings() -> tuple[bool, int]:
    with _db() as c:
        row = c.execute("select enable_connect, connect_port from preferences_table").fetchone()
    enabled, port = (bool(row[0]), int(row[1])) if row else (False, -1)
    return enabled, port if port > 0 else DEFAULT_PORT


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]| - .*$", " ", s.lower())  # drop "(feat. …)", " - Sped Up"
    return " ".join(re.findall(r"[a-z0-9]+", s))


def find(query: str, tracks: list[dict]) -> dict | None:
    """Best match for 'song', 'song by artist' or 'artist' among `tracks`."""
    q = _norm(query)
    title_q, _, artist_q = q.partition(" by ")
    best, best_score = None, 0.0
    for t in tracks:
        name = _norm(t.get("name", ""))
        artists = " ".join(_norm(a.get("name", "")) for a in t.get("artists") or [])
        if not name:
            continue
        score = difflib.SequenceMatcher(None, title_q, name).ratio()
        if title_q and (title_q == name or f" {title_q} " in f" {name} "):
            score = max(score, 0.9 + 0.1 * len(title_q) / max(len(name), 1))
        if artist_q:
            score = score * 0.7 + 0.3 * difflib.SequenceMatcher(None, artist_q, artists).ratio()
        elif title_q in artists.split() or (len(title_q) > 3 and title_q in artists):
            score = max(score, 0.75)  # "play something by Powfu" -> any of theirs
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= 0.72 else None


def _describe(t: dict) -> str:
    artists = ", ".join(a["name"] for a in (t.get("artists") or [])[:2])
    return f"{t['name']}" + (f" by {artists}" if artists else "")


def _player() -> str | None:
    names = subprocess.run(["busctl", "--user", "list", "--no-legend"], capture_output=True,
                           text=True, timeout=5).stdout  # fmt: skip
    return next((ln.split()[0] for ln in names.splitlines()
                 if ln.startswith("org.mpris.MediaPlayer2.spotube")), None)  # fmt: skip


def _mpris(method: str) -> bool:
    player = _player()
    if player:
        subprocess.run(["busctl", "--user", "call", player, "/org/mpris/MediaPlayer2",
                        "org.mpris.MediaPlayer2.Player", method], capture_output=True, timeout=5)  # fmt: skip
    return player is not None


def _mpris_play() -> bool:
    return _mpris("Play")


def now_playing() -> tuple[str, str, bool]:
    """(title, first artist, is playing) from Spotube's MPRIS."""
    player = _player()
    if not player:
        return "", "", False

    def get(prop: str) -> str:
        return subprocess.run(["busctl", "--user", "get-property", player, "/org/mpris/MediaPlayer2",
                               "org.mpris.MediaPlayer2.Player", prop],
                              capture_output=True, text=True, timeout=5).stdout  # fmt: skip

    md = get("Metadata")
    title = re.search(r'"xesam:title" s "((?:[^"\\]|\\.)*)"', md)
    artist = re.search(r'"xesam:artist" as \d+ "((?:[^"\\]|\\.)*)"', md)
    return (title.group(1) if title else "", artist.group(1) if artist else "",
            "Playing" in get("PlaybackStatus"))  # fmt: skip


# Spotube's layout in window pixels (measured maximized at 1853x1048; the sidebar and
# lists are anchored top-left, dialogs to the window centre).
SEARCH_ITEM = (79, 110)  # sidebar "Search"
PLAYLISTS_ITEM = (83, 283)  # sidebar Library > "Playlists"
SEARCH_BOX_Y = 61
FIRST_ROW = (330, 177)  # first song in search results (title)
ROW_THUMB = (251, 157, 291, 197)  # its album art
ROW_TEXT = (300, 160, 700, 195)  # its title/artist text
FILTER_BOX = (300, 65)  # Library > Playlists "Filter your playlists..."
FIRST_TILE = (277, 232)  # first playlist tile
TILE_ART = (212, 160, 344, 300)
TILE_PLAY = (325, 288)  # the play button shown on hover
DIALOG_OK = (163, 41)  # "Ok" of the clear-the-queue dialog, from the window centre
SIDEBAR = (20, 60, 190, 200)  # dims when a dialog is open
MIN_SIZE = (1100, 700)


def _matches(query: str, title: str, artist: str) -> bool:
    want = _norm(query).partition(" by ")[0].split()
    got = f"{_norm(title)} {_norm(artist)}"
    return bool(want) and sum(w in got for w in want) >= max(1, len(want) // 2 + len(want) % 2)


def _stats(img, box) -> tuple[float, float]:
    """(mean, spread) of brightness in a region: art and text have spread, empty bg not."""
    from PIL import ImageStat

    st = ImageStat.Stat(img.crop(box).convert("L"))
    return st.mean[0], st.stddev[0]


def _diff(a, b, box) -> float:
    from PIL import ImageChops, ImageStat

    return float(
        ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box)).convert("L")).mean[0]
    )


class Spotube:
    """Drive Spotube's window: focus, click by layout, look via screenshots."""

    win: Window  # set on entry

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.before: Window | None = None  # the window the user was in

    async def __aenter__(self) -> "Spotube":
        wins = await list_windows()
        self.before = next((w for w in wins if w.focused), None)
        win = find_window("spotube", wins)
        if win is None:
            subprocess.Popen(["spotube"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)  # fmt: skip
            for _ in range(60):
                await asyncio.sleep(0.5)
                if find_window("spotube", await list_windows()):
                    break
            else:
                raise InputError("Spotube didn't open")
        # It opens small, then maximizes: wait until its size has settled.
        last = None
        for _ in range(16):
            win = find_window("spotube", await list_windows())
            if win and last and (win.x, win.y, win.width, win.height) == last:
                break
            last = win and (win.x, win.y, win.width, win.height)
            await asyncio.sleep(0.5)
        if win is None:
            raise InputError("Spotube's window disappeared")
        if win.width < MIN_SIZE[0] or win.height < MIN_SIZE[1]:
            raise InputError("the Spotube window is too small for TARS; maximize it and ask again")
        await self.focus(win)
        self.kb = Keyboard()
        await self.kb.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.kb.__aexit__(*exc)
        if self.before is not None and self.before.id != self.win.id:
            with contextlib.suppress(Exception):
                await activate(self.before)  # back to what the user was doing

    async def focus(self, win: Window | None = None) -> None:
        win = win or find_window("spotube", await list_windows())
        if win and not win.focused:
            await activate(win)
            await asyncio.sleep(0.4)
            win = find_window("spotube", await list_windows())
        if win is None or not win.focused:
            raise InputError("couldn't bring Spotube to the front; nothing was clicked")
        self.win = win

    async def click(self, at: tuple[int, int], **kw) -> None:
        await self.focus()  # never click into another window
        await self.kb.click(self.win.x + at[0], self.win.y + at[1], **kw)

    async def snap(self):
        from PIL import Image

        path = await take_screenshot()
        try:
            img = Image.open(path)
            w = self.win
            return img.crop((w.x, w.y, w.x + w.width, w.y + w.height)).copy()
        finally:
            path.unlink(missing_ok=True)

    async def confirm_dialog(self, before) -> bool:
        """If a dialog dimmed the window (clear-the-queue), press its Ok."""
        await asyncio.sleep(0.9)
        after = await self.snap()
        if _stats(after, SIDEBAR)[0] < 0.75 * _stats(before, SIDEBAR)[0]:
            await self.click(
                (self.win.width // 2 + DIALOG_OK[0], self.win.height // 2 + DIALOG_OK[1])
            )
            return True
        return False


async def _wait_playing(changed_from: str, query: str = "") -> tuple[str, str]:
    title = artist = ""
    for _ in range(12):
        await asyncio.sleep(1)
        title, artist, playing = now_playing()
        if playing and (_matches(query, title, artist) if query else title != changed_from):
            break
    return title, artist


async def play_by_search(ctx: Context, query: str) -> str:
    """Search Spotube and play the top song (Spotube may clear the queue; Ok)."""
    ctx.actions.append(f"spotube search {query!r}")
    if not ctx.desktop:
        return f"playing the top Spotube result for {query!r} (dry run)"
    try:
        async with Spotube(ctx) as sp:
            await sp.click(SEARCH_ITEM)
            await asyncio.sleep(0.8)
            await sp.click((sp.win.width // 2, SEARCH_BOX_Y))
            await sp.kb.combo("ctrl+a")
            await sp.kb.type(query)
            old = await sp.snap()  # results of an earlier search may still be showing
            await sp.focus()
            await sp.kb.combo("Enter")
            for _ in range(12):  # wait for this query's results
                await asyncio.sleep(0.7)
                now = await sp.snap()
                if _stats(now, ROW_THUMB)[1] > 18 and (
                    _diff(old, now, ROW_TEXT) > 4 or _stats(old, ROW_THUMB)[1] <= 18
                ):
                    break
            else:
                if _stats(now, ROW_THUMB)[1] <= 18:
                    return f"error: Spotube showed no songs for {query!r}"
            before = now
            await sp.click(FIRST_ROW)
            asked = await sp.confirm_dialog(before)
            title, artist = await _wait_playing("", query)
    except (NoExtension, InputError) as e:
        return f"error: {e}"
    if not title:
        return "error: Spotube didn't start playing; don't retry, tell the user"
    note = " (Spotube replaced the queue)" if asked else ""
    if not _matches(query, title, artist):
        return f"played {title} by {artist}, the top result for {query!r}; it may not be the one meant. Don't retry{note}"
    return f"playing {title} by {artist} in Spotube{note}"


def _current_playlist() -> str:
    """Name of the playlist Spotube's queue came from, via its history (best effort)."""
    try:
        with _db() as c:
            row = c.execute("select collections from audio_player_state_table limit 1").fetchone()
            cid = (row[0] or "").split(",")[0] if row else ""
            for (data,) in c.execute(
                "select data from history_table where type = 'playlist' order by created_at desc"
            ):
                d = json.loads(data)
                if cid and cid in (d.get("id"), d.get("externalUri", "")):
                    return str(d.get("name", ""))
    except (sqlite3.Error, json.JSONDecodeError):
        pass
    return ""


GENERIC = {"my", "the", "a", "playlist", "playlists", "songs", "song", "music", "tracks", "please"}


def filter_words(name: str) -> str:
    """'my liked songs playlist' -> 'liked': generic words make Spotube's fuzzy filter
    match the wrong playlist ('songs' matched 'Best English Songs', not 'Liked Tracks')."""
    words = [w for w in _norm(name).split() if w not in GENERIC]
    return " ".join(words) or name


async def play_playlist(ctx: Context, name: str) -> str:
    """Library > Playlists, filter by name, play the first match."""
    name = filter_words(name)
    ctx.actions.append(f"spotube playlist {name!r}")
    if not ctx.desktop:
        return f"playing the playlist {name!r} (dry run)"
    try:
        async with Spotube(ctx) as sp:
            playing_before = now_playing()[0]
            await sp.click(PLAYLISTS_ITEM)
            await asyncio.sleep(1.0)
            await sp.click(FILTER_BOX)
            await sp.kb.combo("ctrl+a")
            await sp.kb.type(name)
            await asyncio.sleep(1.0)
            prev = await sp.snap()
            for _ in range(12):  # wait until the filtered list has loaded and stopped changing
                await asyncio.sleep(0.6)
                img = await sp.snap()
                if _stats(img, TILE_ART)[1] > 18 and _diff(prev, img, TILE_ART) < 2:
                    break
                prev = img
            else:
                if _stats(img, TILE_ART)[1] <= 18:
                    return f"error: no playlist matching {name!r} in the library"
            await sp.focus()
            await sp.kb.move_to(sp.win.x + FIRST_TILE[0], sp.win.y + FIRST_TILE[1])
            await asyncio.sleep(0.6)  # its play button appears on hover
            await sp.click(TILE_PLAY)
            await sp.confirm_dialog(img)
            title, artist = await _wait_playing(playing_before)
    except (NoExtension, InputError) as e:
        return f"error: {e}"
    if not title or title == playing_before:
        return "error: the playlist didn't start; don't retry, tell the user"
    which = _current_playlist()
    return f"playing the playlist {which or name!r}: {title} by {artist}"


def _listening_ports() -> list[int]:
    """Ports Spotube listens on, from `ss` (Connect may pick its port itself)."""
    out = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, timeout=5).stdout
    return [int(m.group(1)) for line in out.splitlines() if '"spotube"' in line
            if (m := re.search(r":(\d+)\s", line))]  # fmt: skip


async def _send(port: int, event: dict) -> None:
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws", open_timeout=3, max_size=None) as ws:
        await ws.send(json.dumps(event))
        await asyncio.sleep(0.3)  # let Spotube read it before the socket closes


def load_event(tracks: list[dict], index: int) -> dict:
    return {"type": "load",
            "data": {"runtimeType": "playlist", "tracks": tracks, "collection": None, "initialIndex": index}}  # fmt: skip


async def play_music(ctx: Context, song: str = "", playlist: str = "") -> str:
    if not DB.exists():
        return "error: Spotube isn't set up on this laptop"
    if playlist:
        return await play_playlist(ctx, playlist)
    if _norm(song) in ANY_SONG:
        ctx.actions.append("spotube resume")
        if ctx.desktop and not _mpris_play():
            return "error: Spotube isn't running; open it first (open_app spotube)"
        return "resumed Spotube" + ("" if ctx.desktop else " (dry run)")
    queue, hist = library()
    track = find(song, queue) or find(song, hist)
    if track is None or (ctx.desktop and not connect_settings()[0]):
        return await play_by_search(ctx, song)
    in_queue = next((i for i, t in enumerate(queue) if t.get("id") == track.get("id")), None)
    event = load_event(queue, in_queue) if in_queue is not None else load_event([track], 0)
    ctx.actions.append(f"spotube play {track.get('name')!r}")
    if not ctx.desktop:
        return f"playing {_describe(track)} (dry run)"
    _, port = connect_settings()
    for p in dict.fromkeys([port, *_listening_ports()]):
        try:
            await _send(p, event)
            break
        except (OSError, websockets.WebSocketException, TimeoutError):
            continue
    else:
        return "error: couldn't reach Spotube; is it open?"
    return f"playing {_describe(track)} in Spotube"


def register(reg: Registry):
    reg.tool(
        "play_music",
        "Play music in Spotube: a song ('Believer', 'death bed by Powfu') or one of the user's "
        "playlists ('phonk', 'liked songs'). Both empty = resume. Pause/next/previous: media_control.",
        obj([], song={"type": "string"}, playlist={"type": "string"}),
        tier=Tier.T1,
        speak="Playing",
    )(play_music)
