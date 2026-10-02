"""
Your own documents, searchable: text, Markdown, code notes and PDFs under the folders
you choose (Documents by default) are split into passages and indexed with SQLite
full-text search in ~/.local/share/tars/docs.db. Only changed files are re-read.
Hidden folders and secret paths are never indexed.
"""

import os
import re
import sqlite3
import subprocess
from pathlib import Path

from tars import TARS_HOME
from tars.agent.policy import check_read, resolve
from tars.agent.tools import Context, Denied, Registry, obj

DB = TARS_HOME / "docs.db"
TEXT = {
    ".txt",
    ".md",
    ".rst",
    ".org",
    ".tex",
    ".csv",
    ".py",
    ".ipynb",
    ".json",
    ".yaml",
    ".yml",
    ".html",
}
SKIP = {"node_modules", "venv", ".venv", "__pycache__", "build", "dist"}
MAX_FILE = 5_000_000
CHUNK = 900
SCHEMA = """
create table if not exists files (path text primary key, mtime real);
create virtual table if not exists passages using fts5(path unindexed, place unindexed, text);
"""


def _db(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DB)
    db.executescript(SCHEMA)
    return db


def _read(p: Path) -> list[tuple[str, str]]:
    """[(place, text)]: pages for PDFs, the whole file otherwise."""
    if p.suffix.lower() == ".pdf":
        out = subprocess.run(
            ["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=60
        ).stdout
        return [(f"page {i}", page) for i, page in enumerate(out.split("\f"), 1) if page.strip()]
    return [("", p.read_text(errors="replace"))]


def _chunks(text: str) -> list[str]:
    paras = [q.strip() for q in re.split(r"\n\s*\n", text) if q.strip()]
    out, cur = [], ""
    for para in paras:
        if len(cur) + len(para) > CHUNK and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return [c[: CHUNK * 2] for c in out]


def index(home: Path, folders: list[Path], db_path: Path | None = None) -> tuple[int, int]:
    """(files indexed now, files skipped as unchanged)."""
    db = _db(db_path)
    done = same = 0
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP]
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() not in TEXT | {".pdf"} or name.startswith("."):
                    continue
                try:
                    check_read(p, home)
                    st = p.stat()
                except (Denied, OSError):
                    continue
                if st.st_size > MAX_FILE:
                    continue
                row = db.execute("select mtime from files where path = ?", (str(p),)).fetchone()
                if row and row[0] == st.st_mtime:
                    same += 1
                    continue
                try:
                    parts = _read(p)
                except (OSError, subprocess.SubprocessError):
                    continue
                db.execute("delete from passages where path = ?", (str(p),))
                for place, text in parts:
                    for c in _chunks(text):
                        db.execute(
                            "insert into passages(path, place, text) values (?, ?, ?)",
                            (str(p), place, c),
                        )
                db.execute(
                    "insert or replace into files(path, mtime) values (?, ?)", (str(p), st.st_mtime)
                )
                done += 1
    db.commit()
    return done, same


def search(query: str, limit: int = 5, db_path: Path | None = None) -> list[tuple[str, str, str]]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    if not words:
        return []
    q = " OR ".join(f'"{w}"*' for w in words[:12])
    db = _db(db_path)
    rows = db.execute(
        "select path, place, snippet(passages, 2, '[', ']', ' … ', 40) from passages "
        "where passages match ? order by bm25(passages) limit ?",
        (q, limit * 4),
    ).fetchall()
    out: list[tuple[str, str, str]] = []
    per_file: dict[str, int] = {}  # at most 2 passages per file, so several files show up
    for a, b, c in rows:
        per_file[a] = per_file.get(a, 0) + 1
        if per_file[a] <= 2:
            out.append((str(a), str(b), str(c)))
    return out[:limit]


def _db_for(ctx: Context) -> Path:
    """The index for the home TARS works in (a throwaway one in evals)."""
    return DB if ctx.home.resolve() == Path.home().resolve() else ctx.home / ".tars-docs.db"


def register(reg: Registry):
    def index_documents(ctx: Context, folder: str = "~/Documents") -> str:
        d = resolve(folder, ctx.home)
        check_read(d, ctx.home)
        if not d.is_dir():
            return f"error: {folder} is not a folder"
        done, same = index(ctx.home, [d], _db_for(ctx))
        return f"indexed {done} file(s) in {folder} ({same} unchanged)"

    def search_documents(ctx: Context, query: str) -> str:
        db = _db_for(ctx)
        if not db.exists() and (ctx.home / "Documents").is_dir():
            index(ctx.home, [ctx.home / "Documents"], db)
        hits = search(query, db_path=db)
        if not hits:
            return f"nothing in your indexed documents matches {query!r} (index_documents adds a folder)"
        home = str(ctx.home)
        return "\n\n".join(
            f"[{i}] {path.replace(home, '~')}{f' ({place})' if place else ''}: {text}"
            for i, (path, place, text) in enumerate(hits, 1)
        )

    folder = {"type": "string", "description": "default ~/Documents"}
    reg.tool("index_documents", "Index a folder's documents (text, notes, PDFs) so search_documents can find them.",
             obj([], folder=folder))(index_documents)  # fmt: skip
    reg.tool("search_documents", "Search the user's own documents and PDFs for a topic; returns passages with "
             "the file they're from.", obj(["query"], query={"type": "string"}), speak="Searching your documents")(search_documents)  # fmt: skip
