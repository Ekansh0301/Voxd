"""Split text into word-limited chunks at natural boundaries (e.g. for sites
that convert at most N words at a time)."""

import re


def _words(s: str) -> int:
    return len(s.split())


def _split_long(sentence: str, limit: int) -> list[str]:
    """A single sentence over the limit: split at , ; : first, then by words."""
    parts, cur = [], ""
    for piece in re.split(r"(?<=[,;:])\s+", sentence):
        if _words(piece) > limit:
            words = piece.split()
            for i in range(0, len(words), limit):
                parts.append(" ".join(words[i : i + limit]))
            continue
        if cur and _words(cur) + _words(piece) > limit:
            parts.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_words(text: str, limit: int = 190) -> list[str]:
    """
    Chunks of at most `limit` words. Paragraph breaks are kept inside a chunk,
    chunks end at sentence boundaries where possible, and joining the chunks
    with "\\n\\n" or " " reproduces the text's words in order.
    """
    chunks: list[str] = []
    cur: list[str] = []  # paragraphs in the current chunk
    cur_words = 0

    def flush():
        nonlocal cur, cur_words
        if cur:
            chunks.append("\n\n".join(cur))
        cur, cur_words = [], 0

    for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        sentences = []
        for s in re.split(r"(?<=[.!?])\s+", para):
            sentences += _split_long(s, limit) if _words(s) > limit else [s]
        para_buf = ""
        for s in sentences:
            if cur_words + _words(para_buf) + _words(s) > limit:
                if para_buf:
                    cur.append(para_buf)
                flush()
                para_buf = s
            else:
                para_buf = f"{para_buf} {s}".strip()
        if para_buf:
            cur.append(para_buf)
            cur_words += _words(para_buf)
    flush()
    return chunks
