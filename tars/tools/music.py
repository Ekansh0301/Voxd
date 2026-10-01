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
import difflib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import websockets

from tars.agent.tools import Context, Registry, Tier, obj
from tars.perception.keyboard import InputError, Keyboard
from tars.perception.windows import NoExtension, activate, list_windows
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


# Spotube's layout, in window pixels (checked at 1853x1048): sidebar "Search", the
# search box, the first song row, and "Play next" in the row's menu (right-anchored).
SEARCH_ITEM = (79, 110)
SEARCH_BOX_Y = 61
FIRST_ROW = (330, 177)
PLAY_NEXT = (-146, 270)  # x from the window's right edge
MIN_SIZE = (1100, 700)


def _matches(query: str, title: str, artist: str) -> bool:
    want = _norm(query).partition(" by ")[0].split()
    got = f"{_norm(title)} {_norm(artist)}"
    return bool(want) and sum(w in got for w in want) >= max(1, len(want) // 2 + len(want) % 2)


async def play_by_search(ctx: Context, query: str) -> str:
    """Search Spotube for `query` and play the top result next (queue kept)."""
    ctx.actions.append(f"spotube search {query!r}")
    if not ctx.desktop:
        return f"playing the top Spotube result for {query!r} (dry run)"
    try:
        wins = await list_windows()
        before = next((w for w in wins if w.focused), None)
        win = find_window("spotube", wins)
        if win is None:
            subprocess.Popen(["spotube"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)  # fmt: skip
            for _ in range(30):
                await asyncio.sleep(1)
                if win := find_window("spotube", await list_windows()):
                    break
            else:
                return "error: Spotube didn't open"
            await asyncio.sleep(3)  # let it finish loading its home page
        if win.width < MIN_SIZE[0] or win.height < MIN_SIZE[1]:
            return (
                "error: the Spotube window is too small for TARS to use; maximize it and ask again"
            )
        await activate(win)
        await asyncio.sleep(0.4)
        win = find_window("spotube", await list_windows())
        if win is None or not win.focused:
            return "error: couldn't bring Spotube to the front"
        x0, y0 = win.x, win.y
        async with Keyboard() as kb:
            await kb.click(x0 + SEARCH_ITEM[0], y0 + SEARCH_ITEM[1])
            await asyncio.sleep(0.7)
            await kb.click(x0 + win.width // 2, y0 + SEARCH_BOX_Y)
            await kb.combo("ctrl+a")
            await kb.type(query)
            await kb.combo("Enter")
            await asyncio.sleep(2.5)  # results load from the network
            now = find_window("spotube", await list_windows())
            if now is None or not now.focused:  # the user switched away: don't click blindly
                return "error: Spotube lost focus while searching; nothing was played"
            await kb.click(x0 + FIRST_ROW[0], y0 + FIRST_ROW[1], button="right")
            await asyncio.sleep(0.8)
            await kb.click(x0 + win.width + PLAY_NEXT[0], y0 + PLAY_NEXT[1])
            await asyncio.sleep(0.6)
        _mpris("Next")
        title = artist = ""
        for _ in range(10):
            await asyncio.sleep(1)
            title, artist, playing = now_playing()
            if playing and _matches(query, title, artist):
                break
        if before is not None and before.id != win.id:
            await activate(before)  # back to what the user was doing
    except NoExtension as e:
        return f"error: {e}"
    except InputError as e:
        return f"error: {e}"
    if not title:
        return "error: Spotube didn't start playing; check its window"
    if not _matches(query, title, artist):
        return f"played {title} by {artist}, which may not be what was asked for"
    return f"playing {title} by {artist} in Spotube (your queue is kept)"


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


async def play_music(ctx: Context, song: str = "") -> str:
    if not DB.exists():
        return "error: Spotube isn't set up on this laptop"
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
        "Play any song in Spotube: 'Believer', 'death bed by Powfu'. "
        "Leave song empty to just resume music. Pause/next/previous: media_control.",
        obj([], song={"type": "string"}),
        tier=Tier.T1,
        speak="Playing",
    )(play_music)
