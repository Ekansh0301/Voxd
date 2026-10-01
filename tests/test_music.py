import asyncio
import json
import sqlite3

import pytest
import websockets

from tars.agent.tools import Context
from tars.tools import music

TRACKS = [
    {"id": "1", "name": "Zinda", "artists": [{"id": "a", "name": "Siddharth Mahadevan"}]},
    {
        "id": "2",
        "name": "death bed (coffee for your head)",
        "artists": [{"id": "b", "name": "Powfu"}],
    },
    {
        "id": "3",
        "name": "Miss You - Sped Up Version",
        "artists": [{"id": "c", "name": "Oliver Tree"}],
    },
]
HISTORY = {"id": "9", "name": "Kun Faya Kun", "artists": [{"id": "d", "name": "A.R. Rahman"}]}


@pytest.fixture
def spotube(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    c = sqlite3.connect(db)
    c.execute("create table audio_player_state_table (id, tracks)")
    c.execute("create table history_table (id, created_at, type, item_id, data)")
    c.execute("create table preferences_table (enable_connect, connect_port, spotify_secret)")
    c.execute("insert into audio_player_state_table values (0, ?)", (json.dumps(TRACKS),))
    c.execute("insert into history_table values (1, 1, 'track', '9', ?)", (json.dumps(HISTORY),))
    c.execute("insert into preferences_table values (1, 0, 'do-not-read')")
    c.commit()
    c.close()
    monkeypatch.setattr(music, "DB", db)
    return db


@pytest.mark.parametrize("query,expected", [
    ("zinda", "1"), ("Death Bed by powfu", "2"), ("powfu", "2"), ("miss you", "3"), ("bohemian rhapsody", None),
])  # fmt: skip
def test_find(query, expected):
    t = music.find(query, TRACKS)
    assert (t and t["id"]) == expected


def test_play_sends_load_with_whole_queue(spotube, monkeypatch):
    got: list[dict] = []

    async def scenario():
        async def handler(ws):
            got.append(json.loads(await ws.recv()))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr(music, "DEFAULT_PORT", port)
            return await music.play_music(Context(desktop=True), "death bed")

    out = asyncio.run(scenario())
    assert out == "playing death bed (coffee for your head) by Powfu in Spotube"
    assert got[0]["type"] == "load" and got[0]["data"]["initialIndex"] == 1
    assert [t["id"] for t in got[0]["data"]["tracks"]] == ["1", "2", "3"]


def test_history_song_and_unknown_song(spotube):
    ctx = Context(desktop=False)
    assert "Kun Faya Kun" in asyncio.run(music.play_music(ctx, "kun faya kun"))
    assert "dry run" in asyncio.run(music.play_music(ctx, "bohemian rhapsody"))
    assert asyncio.run(music.play_music(ctx, "some music")).startswith("resumed")


def test_connect_off_or_unknown_song_uses_search(spotube, monkeypatch):
    searched = []

    async def fake_search(ctx, query):
        searched.append(query)
        return f"playing {query} (search)"

    monkeypatch.setattr(music, "play_by_search", fake_search)
    c = sqlite3.connect(spotube)
    c.execute("update preferences_table set enable_connect = 0")
    c.commit()
    c.close()
    assert asyncio.run(music.play_music(Context(desktop=True), "zinda")) == "playing zinda (search)"
    assert "(search)" in asyncio.run(music.play_music(Context(desktop=False), "bohemian rhapsody"))
    assert searched == ["zinda", "bohemian rhapsody"]


def test_matches():
    assert music._matches("Believer", "Believer", "Imagine Dragons")
    assert music._matches("death bed by powfu", "death bed (coffee for your head)", "Powfu")
    assert not music._matches("Believer", "Subhanallah", "Pritam")
