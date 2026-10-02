"""
Clicking things an app doesn't expose to accessibility (Spotube, games, canvases):
find them in a screenshot of the window, then click with the pointer.
  - text labels ("Search", "Liked Tracks"): OCR (tesseract), exact to a few pixels
  - icons and anything without text ("the play button"): the Brain's vision, which
    answers with a box on a 0-1000 grid (within ~7 px in tests)
Use read_screen + click first: names from the accessibility tree are exact.
"""

import difflib
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.perception.atspi import RISKY_WORDS
from tars.perception.windows import NoExtension, Window, activate, list_windows
from tars.perception.windows import find as find_window


@dataclass
class Hit:
    x: int  # centre, in window pixels
    y: int
    how: str  # "text" or "vision"
    text: str = ""


async def _shot(win: Window):
    from PIL import Image

    from tars.perception.screenshot import take_screenshot

    path = await take_screenshot()
    try:
        return Image.open(path).crop((win.x, win.y, win.x + win.width, win.y + win.height)).copy()
    finally:
        path.unlink(missing_ok=True)


def ocr_find(img, target: str) -> list[Hit]:
    """Every place the words of `target` appear in order on one line."""
    from PIL import ImageOps, ImageStat

    if not shutil.which("tesseract"):
        return []
    g = ImageOps.grayscale(img)
    if ImageStat.Stat(g).mean[0] < 110:  # dark theme: dark text on light reads better
        g = ImageOps.invert(g)
    g = g.resize((g.width * 2, g.height * 2))
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        g.save(f.name)
        tsv = subprocess.run(["tesseract", f.name, "stdout", "--psm", "11", "tsv"],
                             capture_output=True, text=True, timeout=30).stdout  # fmt: skip
    words: dict[tuple, list] = {}
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) > 40:
            key = (c[1], c[2], c[3], c[4])  # page, block, paragraph, line
            words.setdefault(key, []).append((c[11].strip(), *(int(v) // 2 for v in c[6:10])))
    want = [w.lower() for w in re.findall(r"\w+", target)]
    hits = []
    for line in words.values():
        got = [re.sub(r"\W", "", w[0]).lower() for w in line]
        for i in range(len(got) - len(want) + 1):
            if all(
                difflib.SequenceMatcher(None, a, b).ratio() >= 0.85
                for a, b in zip(want, got[i:], strict=False)
            ):
                ws = line[i : i + len(want)]
                x1, y1 = min(w[1] for w in ws), min(w[2] for w in ws)
                x2, y2 = max(w[1] + w[3] for w in ws), max(w[2] + w[4] for w in ws)
                hits.append(Hit((x1 + x2) // 2, (y1 + y2) // 2, "text", " ".join(w[0] for w in ws)))
    return sorted(hits, key=lambda h: (h.y // 20, h.x))  # reading order


def _box(answer: str) -> tuple[float, float, float, float] | None:
    m = re.search(
        r"\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]", answer
    )
    return tuple(float(v) for v in m.groups()) if m else None  # type: ignore[return-value]


async def vision_find(img, target: str) -> Hit | None:
    """The vision model's box for `target`, on its 0-1000 grid. (A zoomed second look
    made it worse in tests: ~55 px off where the first pass was within ~7.)"""
    from tars.tools.vision import ask_image

    buf = io.BytesIO()
    img.save(buf, "PNG")
    q = f"Locate {target}. Reply with only its bounding box as JSON [x1, y1, x2, y2]."
    box = _box(await ask_image(buf.getvalue(), q))
    if not box:
        return None
    W, H = img.size
    return Hit(
        int((box[0] + box[2]) / 2 * W / 1000), int((box[1] + box[3]) / 2 * H / 1000), "vision"
    )


async def click_on_screen(ctx: Context, target: str, window: str = "", index: int = 0,
                          button: str = "left") -> str:  # fmt: skip
    if any(w in target.lower() for w in RISKY_WORDS):
        await ctx.require(Tier.T3, f"click {target!r}")
    ctx.actions.append(f"click on screen {target!r}")
    if not ctx.desktop:
        return f"clicked {target!r} (dry run)"
    from tars.perception.keyboard import InputError, Keyboard

    try:
        wins = await list_windows()
        win = find_window(window, wins) if window else next((w for w in wins if w.focused), None)
        win = win or next((w for w in reversed(wins) if not w.minimized), None)
        if win is None:
            return (
                f"error: no window matching {window!r}" if window else "error: no window to look at"
            )
        if not win.focused:
            await activate(win)
        img = await _shot(win)
        hits = ocr_find(img, target)
        if len(hits) > 1 and not index:
            spots = "; ".join(
                f"{i}: {h.text!r} at ({h.x}, {h.y})" for i, h in enumerate(hits[:8], 1)
            )
            return (f"{len(hits)} places show {target!r} in {win.label!r} (x from the left, y from the top "
                    f"of the window): {spots}. Call again with index=N.")  # fmt: skip
        hit = hits[index - 1] if hits and 0 < index <= len(hits) else hits[0] if hits else None
        if hit is None:
            hit = await vision_find(img, target)
        if hit is None:
            return f"error: couldn't find {target!r} in {win.label!r}"
        if hit.text and any(w in hit.text.lower() for w in RISKY_WORDS):
            await ctx.require(Tier.T3, f"click {hit.text!r}")
        now = find_window(win.wm_class, await list_windows()) or win
        if not now.focused:
            raise Denied(f"{win.label!r} isn't in front; not clicking blind")
        async with Keyboard() as kb:
            await kb.click(now.x + hit.x, now.y + hit.y, button=button)
    except (NoExtension, InputError) as e:
        return f"error: {e}"
    found = f"by its text {hit.text!r}" if hit.how == "text" else "by looking (vision, approximate)"
    return f"clicked {target!r} in {win.label!r}, found {found} at ({hit.x}, {hit.y}); check the result"


def register(reg: Registry):
    reg.tool(
        "click_on_screen",
        "Click something by how it looks, for apps that read_screen can't see into (e.g. "
        "Spotube): a text label ('Search') or a described icon ('the play button'). "
        "Prefer read_screen + click when that works.",
        obj(["target"], target={"type": "string"}, window={"type": "string", "description": "app to look at; default the one in front"},
            index={"type": "integer", "description": "which match, if several"}),
        tier=Tier.T1,
    )(click_on_screen)  # fmt: skip
