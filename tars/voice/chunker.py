"""
Turn streamed LLM text into speakable chunks as early as possible.

The first chunk is cut at the first clause break (comma, semicolon, colon) or
sentence end once it has a few words, so TTS can start while the model is
still writing. Later chunks are whole sentences; very short ones are merged
with the next so the voice doesn't sound choppy.
"""

import re

ABBREVIATIONS = {"e.g", "i.e", "etc", "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "approx"}
FIRST_MIN_WORDS = 2  # "Sure thing," starts audio; a lone "Okay," would sound choppy
MERGE_BELOW_WORDS = 4
# A first sentence with no comma would otherwise be synthesised whole before any
# audio plays. Cut it before a joining word after a few words, or after 10 words.
JOINERS = {"and", "but", "or", "so", "because", "since", "which", "that", "while",
           "although", "though", "if", "when", "unless", "until", "then"}  # fmt: skip
FIRST_JOINER_AFTER = 4
FIRST_MAX_WORDS = 10


def clean_for_speech(text: str) -> str:
    """Remove what TTS would read badly: markdown, code, raw URLs, home paths."""
    text = re.sub(r"```[\s\S]*?```", " code block ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+", "", text)
    text = re.sub(r"https?://(?:www\.)?([^/\s]+)\S*", r"\1", text)
    text = re.sub(r"/home/[\w.-]+/", "home folder ", text)
    return re.sub(r"\s+", " ", text).strip()


def _words(s: str) -> int:
    return len(s.split())


class SpeechChunker:
    def __init__(self):
        self.buf = ""
        self.pending = ""  # a short sentence waiting to be merged with the next
        self.first_sent = False

    def _cut_at(self) -> int | None:
        """Index just after a usable break in self.buf, or None if none yet."""
        for m in re.finditer(r"[.!?…]+[\"')\]]*(?=\s)|\n+|[,;:](?=\s)", self.buf):
            mark = m.group(0)
            if mark[0] in ",;:":
                if self.first_sent:
                    continue  # after the first chunk, only cut at sentence ends
            elif mark[0] == ".":
                prev = re.search(r"(\S+)\.$", self.buf[: m.start() + 1])
                if prev and prev.group(1).lower().rstrip(".") in ABBREVIATIONS:
                    continue
                if re.match(r"\.\d", self.buf[m.start() : m.start() + 2]):
                    continue
            end = m.end()
            if not self.first_sent and _words(self.buf[:end]) < FIRST_MIN_WORDS:
                continue
            return end
        return None

    def _first_fallback_cut(self) -> int | None:
        """For the first chunk only: where to cut a long clause with no punctuation yet."""
        complete = self.buf if self.buf[-1:].isspace() else self.buf.rsplit(None, 1)[0]
        spans = [m.span() for m in re.finditer(r"\S+", complete)]
        for i, (start, _) in enumerate(spans):
            word = complete[start : spans[i][1]].lower().strip(",.")
            if i >= FIRST_JOINER_AFTER and word in JOINERS:
                return start
        if len(spans) > FIRST_MAX_WORDS:
            return spans[FIRST_MAX_WORDS - 1][1]
        return None

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        if not self.first_sent and self.buf.strip() and self._cut_at() is None:
            if (end := self._first_fallback_cut()) is not None:
                piece, self.buf = self.buf[:end], self.buf[end:].lstrip()
                out += self._emit(piece)
        while (end := self._cut_at()) is not None:
            piece, self.buf = self.buf[:end], self.buf[end:].lstrip()
            out += self._emit(piece)
        return out

    def _emit(self, piece: str) -> list[str]:
        text = clean_for_speech(piece)
        if not text:
            return []
        if not self.first_sent:
            self.first_sent = True
            return [text]
        text = f"{self.pending} {text}".strip()
        if _words(text) < MERGE_BELOW_WORDS:
            self.pending = text
            return []
        self.pending = ""
        return [text]

    def flush(self) -> list[str]:
        rest = clean_for_speech(self.buf)
        self.buf = ""
        text = f"{self.pending} {rest}".strip()
        self.pending = ""
        self.first_sent = True
        return [text] if text else []
