"""
Look at the screen with the Brain's vision projector — the fallback for what
the accessibility tree doesn't expose (canvas apps, some displays, images).

The projector reads ~256 image tokens, too coarse for small text on a full
1920x1080 screen, so the model can zoom into a region (each crop is ~4x the
detail). Screenshots go to a private temp file and are deleted after reading.
"""

import base64
import io
import shutil
import tempfile
from pathlib import Path

import httpx

from tars.agent.tools import Context, Registry, obj
from tars.config import load
from tars.llm.client import NO_THINK
from tars.perception.screenshot import take_screenshot

REGIONS = {  # (left, top, right, bottom) as fractions of the screen
    "full": (0, 0, 1, 1), "center": (0.2, 0.2, 0.8, 0.8),
    "top": (0, 0, 1, 0.5), "bottom": (0, 0.5, 1, 1), "left": (0, 0, 0.5, 1), "right": (0.5, 0, 1, 1),
    "top-left": (0, 0, 0.5, 0.5), "top-right": (0.5, 0, 1, 0.5),
    "bottom-left": (0, 0.5, 0.5, 1), "bottom-right": (0.5, 0.5, 1, 1),
}  # fmt: skip


def crop_png(path: Path, region: str, max_side: int = 1280) -> bytes:
    from PIL import Image

    img = Image.open(path).convert("RGB")
    left, top, right, bottom = REGIONS.get(region, REGIONS["full"])
    w, h = img.size
    img = img.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def ask_image(png: bytes, question: str, cfg: dict | None = None) -> str:
    cfg = cfg or load()
    b64 = base64.b64encode(png).decode()
    body = {
        "model": cfg["llm"]["brain"], "max_tokens": 250, "temperature": 0.2, **NO_THINK,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": f"{question}\nAnswer briefly and only from what is visible. "
                                     "If text is too small to read, say so."},
        ]}],
    }  # fmt: skip
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{cfg['llm']['endpoint']}/chat/completions", json=body)
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"]).strip()


async def look_at_screen(ctx: Context, question: str, region: str = "full") -> str:
    if region not in REGIONS:
        return f"error: region must be one of {', '.join(REGIONS)}"
    shot = await take_screenshot(
        keep_permission=load().get("screen", {}).get("keep_screenshot_permission", True)
    )
    with tempfile.TemporaryDirectory(prefix="tars-shot-") as tmp:
        private = Path(tmp) / "screen.png"
        shutil.move(str(shot), private)  # out of ~/Pictures, deleted with the temp dir
        png = crop_png(private, region)
    answer = await ask_image(png, question)
    return f"[{region} of the screen] {answer}"


def register(reg: Registry):
    reg.tool(
        "look_at_screen",
        "Look at the screen image and answer a question about it. Use when read_screen shows "
        "too little. For small text, zoom with a region (top-left, top-right, center, ...).",
        obj(["question"], question={"type": "string"},
            region={"type": "string", "enum": list(REGIONS)}),
        speak="Looking",
    )(look_at_screen)  # fmt: skip
