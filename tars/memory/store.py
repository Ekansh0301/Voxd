"""
Long-term memory in SQLite with FTS5 full-text search (no embeddings yet).

Facts are things you asked TARS to remember; turns are past exchanges.
Vectors (sqlite-vec) can be added later for fuzzier recall.
"""

import re
import sqlite3
import time
from pathlib import Path

from tars import TARS_HOME

SCHEMA = """
create table if not exists facts (id integer primary key, ts real, text text, source text);
create table if not exists turns (id integer primary key, ts real, user text, assistant text);
create virtual table if not exists facts_fts using fts5(text, content='facts', content_rowid='id');
create virtual table if not exists turns_fts using fts5(user, assistant, content='turns', content_rowid='id');
create trigger if not exists facts_ai after insert on facts begin
  insert into facts_fts(rowid, text) values (new.id, new.text); end;
create trigger if not exists facts_ad after delete on facts begin
  insert into facts_fts(facts_fts, rowid, text) values ('delete', old.id, old.text); end;
create trigger if not exists turns_ai after insert on turns begin
  insert into turns_fts(rowid, user, assistant) values (new.id, new.user, new.assistant); end;
"""
STOP = set("a an the is are was were be to of in on at for and or but it this that what who how "
           "i you me my your do does did can could would should please tell about with".split())  # fmt: skip


def _query(text: str) -> str | None:
    """Free text -> FTS5 query matching any meaningful word (prefix match)."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
    return " OR ".join(f'"{w}"*' for w in words[:12]) or None


class Memory:
    def __init__(self, path: Path = TARS_HOME / "memory.db"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def remember(self, text: str, source: str = "user") -> int:
        cur = self.db.execute(
            "insert into facts(ts, text, source) values (?, ?, ?)",
            (time.time(), text.strip(), source),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    def forget(self, fact_id: int) -> bool:
        cur = self.db.execute("delete from facts where id = ?", (fact_id,))
        self.db.commit()
        return cur.rowcount > 0

    def add_turn(self, user: str, assistant: str):
        self.db.execute(
            "insert into turns(ts, user, assistant) values (?, ?, ?)",
            (time.time(), user, assistant),
        )
        self.db.commit()

    def facts(self, query: str | None = None, limit: int = 5) -> list[tuple[int, str]]:
        if query is None:
            rows = self.db.execute("select id, text from facts order by ts desc limit ?", (limit,))
            return list(rows)
        q = _query(query)
        if not q:
            return []
        rows = self.db.execute(
            "select f.id, f.text from facts_fts join facts f on f.id = facts_fts.rowid "
            "where facts_fts match ? order by bm25(facts_fts) limit ?",
            (q, limit),
        )
        return list(rows)

    def turns(self, query: str, limit: int = 3) -> list[tuple[str, str, str]]:
        q = _query(query)
        if not q:
            return []
        rows = self.db.execute(
            "select datetime(t.ts, 'unixepoch', 'localtime'), t.user, t.assistant "
            "from turns_fts join turns t on t.id = turns_fts.rowid "
            "where turns_fts match ? order by bm25(turns_fts) limit ?",
            (q, limit),
        )
        return list(rows)
