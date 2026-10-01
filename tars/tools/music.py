"""
Spotube: "play Zinda", "play death bed by Powfu", "play some music".

Spotube is a Flutter app and exposes no accessibility tree, so it isn't driven by
clicks. Instead:
  - songs are matched against your own Spotube library (the saved queue, i.e.
    your liked songs, plus listening history), read-only from its database.
    Nothing is searched online.
  - a match is played through Spotube Connect, its local WebSocket remote
    (Spotube settings: turn on "Spotube Connect").
  - no particular song ("play some music") resumes Spotube over MPRIS.
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


def _mpris_play() -> bool:
    names = subprocess.run(["busctl", "--user", "list", "--no-legend"], capture_output=True,
                           text=True, timeout=5).stdout  # fmt: skip
    player = next((ln.split()[0] for ln in names.splitlines()
                   if ln.startswith("org.mpris.MediaPlayer2.spotube")), None)  # fmt: skip
    if player:
        subprocess.run(["busctl", "--user", "call", player, "/org/mpris/MediaPlayer2",
                        "org.mpris.MediaPlayer2.Player", "Play"], capture_output=True, timeout=5)  # fmt: skip
    return player is not None


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
    if track is None:
        return (f"error: {song!r} isn't in the user's Spotube liked songs or history. "
                "Searching Spotube's catalogue isn't supported yet; the user can search in Spotube.")  # fmt: skip
    in_queue = next((i for i, t in enumerate(queue) if t.get("id") == track.get("id")), None)
    event = load_event(queue, in_queue) if in_queue is not None else load_event([track], 0)
    ctx.actions.append(f"spotube play {track.get('name')!r}")
    if not ctx.desktop:
        return f"playing {_describe(track)} (dry run)"
    enabled, port = connect_settings()
    if not enabled:
        return (f"error: found {_describe(track)}, but Spotube Connect is off. The user can turn it on "
                "in Spotube's settings (Spotube Connect), then ask again.")  # fmt: skip
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
        "Play a song in Spotube from the user's library: 'Zinda', 'death bed by Powfu'. "
        "Leave song empty to just resume music. Pause/next/previous: media_control.",
        obj([], song={"type": "string"}),
        tier=Tier.T1,
        speak="Playing",
    )(play_music)
