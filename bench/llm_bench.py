"""
LLM benchmark for the GTX 1650: load time, VRAM, prefill/decode speed,
prefix-cache reuse, tool-call accuracy (native tools vs JSON-schema mode),
and screen-reading with the vision projector.

    venv/bin/python -m bench.llm_bench                      # all models, all tests
    venv/bin/python -m bench.llm_bench -m qwen3.5-4b-q4km -t speed,tools

Results go to bench/results/llm-<model>.json; bench/report.py turns them into
docs/BENCHMARKS.md.
"""

import argparse
import base64
import io
import json
import statistics
import time
from pathlib import Path
from typing import Any

from tars import MODELS_DIR
from tars.gpu import PeakVram, vram_total_mib, vram_used_mib
from tars.llm.server import LlamaServer, ServerConfig

HERE = Path(__file__).parent
RESULTS = HERE / "results"
LLM_DIR = MODELS_DIR / "llm"
MMPROJ_4B = LLM_DIR / "qwen3.5-4b-mmproj" / "mmproj-F16.gguf"

MODELS: dict[str, dict[str, Any]] = {
    "qwen3.5-4b-q4km": {"file": "Qwen3.5-4B-Q4_K_M.gguf", "mmproj": MMPROJ_4B},
    "qwen3.5-4b-iq4xs": {"file": "Qwen3.5-4B-IQ4_XS.gguf", "mmproj": MMPROJ_4B},
    "qwen3-4b-2507-q4km": {"file": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"},
    "qwen3.5-2b-q4km": {"file": "Qwen3.5-2B-Q4_K_M.gguf"},
    "qwen3.5-0.8b-cpu": {
        "file": "Qwen3.5-0.8B-Q4_K_M.gguf",
        "gpu_layers": 0,
        "threads": 6,
        # without this llama.cpp still ships big prompt batches to the GPU
        "extra": ["--device", "none"],
    },
}
ALL_TESTS = ["speed", "cache", "tools", "json", "vision"]
# (label, projector on GPU?, --image-max-tokens, ctx override)
VISION_VARIANTS = [
    ("cpu, 1024 img tok", False, None, None),
    ("cpu, 256 img tok", False, 256, None),
    ("gpu, 256 img tok, ctx 4k", True, 256, 4096),
]

SYSTEM = (
    "You are TARS, a voice assistant that controls the user's Ubuntu laptop (Firefox browser, "
    "Outlook web for mail). If the user asks you to do something, call exactly one tool. "
    "Use delegate for tasks that need several steps (mail, forms, research, fixing code, "
    "organising files). If the user is just chatting or asks a general-knowledge question, "
    "answer directly in one or two sentences without any tool.\n"
    "Websites (use open_url, not open_app): Outlook mail, YouTube, GitHub, WhatsApp Web, "
    "ChatGPT, Gemini, Claude, LeetCode, LinkedIn."
)
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}

FILLER = (
    "The quick agent reads the accessibility tree of the focused window, finds the button "
    "named Compose, checks that it is enabled, clicks it, and then verifies that a new "
    "message editor appeared before typing anything. "
)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _prompt_of(server: LlamaServer, n_tokens: int, salt: str) -> list[int]:
    """A prompt of exactly n_tokens tokens that shares no prefix with other salts."""
    toks = server.tokenize(f"[{salt}] " + FILLER * (n_tokens // 30 + 2))
    return toks[:n_tokens]


# ── tests ────────────────────────────────────────────────────────────────────
def test_speed(server: LlamaServer) -> dict:
    out: dict = {"prefill_tps": {}, "prefill_ms": {}}
    for n in (512, 2048, 4096):
        r = server.complete(_prompt_of(server, n, f"speed-{n}"), n_predict=1, cache_prompt=False)
        t = r["timings"]
        out["prefill_tps"][n] = round(t["prompt_per_second"], 1)
        out["prefill_ms"][n] = round(t["prompt_ms"])
    r = server.complete(
        "Write a long story about a robot named TARS.", n_predict=128, ignore_eos=True
    )
    out["decode_tps"] = round(r["timings"]["predicted_per_second"], 1)
    return out


def test_cache(server: LlamaServer) -> dict:
    """Same ~2.5k-token prefix (like a cached role prompt), different short suffixes."""
    prefix = server.tokenize("[role-prefix] " + FILLER * 90)[:2500]
    cold = server.complete(prefix + server.tokenize(" Question one?"), n_predict=1)["timings"]
    warm = server.complete(prefix + server.tokenize(" Question two?"), n_predict=1)["timings"]
    return {
        "prefix_tokens": len(prefix),
        "cold_prompt_ms": round(cold["prompt_ms"]),
        "warm_prompt_ms": round(warm["prompt_ms"]),
        "warm_tokens_processed": warm.get("prompt_n"),
        "warm_tokens_from_cache": warm.get("cache_n"),
    }


def _load_prompts() -> list[dict]:
    with open(HERE / "data" / "tool_prompts.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_tools() -> list[dict]:
    return json.loads((HERE / "data" / "tools.json").read_text())  # type: ignore[no-any-return]


def _score(case: dict, tool: str, args: dict) -> tuple[bool, bool]:
    want = case["tool"] if isinstance(case["tool"], list) else [case["tool"]]
    tool_ok = tool in want
    args_ok = tool_ok
    if tool_ok:
        for key, options in case.get("args", {}).items():
            val = str(args.get(key, "")).lower()
            if not any(opt.lower() in val for opt in options):
                args_ok = False
    return tool_ok, args_ok


def _summarise(rows: list[dict]) -> dict:
    lat = [r["ms"] for r in rows]
    return {
        "n": len(rows),
        "tool_acc": round(sum(r["tool_ok"] for r in rows) / len(rows), 3),
        "args_acc": round(sum(r["args_ok"] for r in rows) / len(rows), 3),
        "valid": round(sum(r.get("valid", True) for r in rows) / len(rows), 3),
        "latency_ms_median": round(statistics.median(lat)),
        "latency_ms_p90": round(sorted(lat)[int(len(lat) * 0.9) - 1]),
        "failures": [
            {k: r[k] for k in ("id", "prompt", "got", "args")} for r in rows if not r["args_ok"]
        ],
    }


def test_tools(server: LlamaServer) -> dict:
    """Native tool calling (OpenAI-style tools through the chat template)."""
    tools = _load_tools()
    rows = []
    for case in _load_prompts():
        t0 = time.monotonic()
        r = server.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": case["prompt"]}],
            tools=tools,
            max_tokens=160,
            **NO_THINK,
        )
        ms = (time.monotonic() - t0) * 1000
        msg = r["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        tool, args, valid = "none", {}, True
        if calls:
            fn = calls[0]["function"]
            tool = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                valid = False
        tool_ok, args_ok = _score(case, tool, args)
        rows.append(
            {
                "id": case["id"], "prompt": case["prompt"], "got": tool, "args": args, "ms": ms,
                "tool_ok": tool_ok, "args_ok": args_ok, "valid": valid,
            }
        )  # fmt: skip
    return _summarise(rows)


def test_json(server: LlamaServer) -> dict:
    """The same decisions, but decoded against a JSON schema (grammar-constrained)."""
    tools = _load_tools()
    names = [t["function"]["name"] for t in tools]
    lines = []
    for t in tools:
        fn = t["function"]
        params = ", ".join(fn["parameters"]["properties"])
        lines.append(f"- {fn['name']}({params}): {fn['description']}")
    system = (
        SYSTEM
        + "\n\nTools:\n"
        + "\n".join(lines)
        + '\n\nReply with JSON only: {"tool": <tool name or "none">, "args": {...}, '
        '"say": <short spoken reply>}.'
    )
    schema = {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": names + ["none"]},
            "args": {"type": "object"},
            "say": {"type": "string"},
        },
        "required": ["tool", "args", "say"],
    }
    rows = []
    for case in _load_prompts():
        t0 = time.monotonic()
        r = server.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": case["prompt"]}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "action", "schema": schema},
            },
            max_tokens=160,
            **NO_THINK,
        )
        ms = (time.monotonic() - t0) * 1000
        content = r["choices"][0]["message"].get("content") or ""
        try:
            d = json.loads(content)
            tool, args, valid = d.get("tool", "none"), d.get("args") or {}, True
        except json.JSONDecodeError:
            tool, args, valid = "invalid", {}, False
        tool_ok, args_ok = _score(case, tool, args)
        rows.append(
            {
                "id": case["id"], "prompt": case["prompt"], "got": tool, "args": args, "ms": ms,
                "tool_ok": tool_ok, "args_ok": args_ok, "valid": valid,
            }
        )  # fmt: skip
    return _summarise(rows)


def _dialog_png() -> bytes:
    """A synthetic desktop dialog (no real screen content leaves your session)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1280, 800), (46, 52, 64))
    d = ImageDraw.Draw(img)

    def font(size):
        for name in ("DejaVuSans.ttf", "Ubuntu-R.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    d.rectangle([340, 250, 940, 550], fill=(250, 250, 250), outline=(120, 120, 120), width=2)
    d.rectangle([340, 250, 940, 300], fill=(225, 228, 235))
    d.text((360, 262), "Unsaved changes", fill=(20, 20, 20), font=font(24))
    d.text(
        (360, 330),
        "Save changes to report_final.docx before closing?",
        fill=(30, 30, 30),
        font=font(20),
    )
    d.text(
        (360, 365),
        "Your changes will be lost if you don't save them.",
        fill=(90, 90, 90),
        font=font(17),
    )
    for x, label in ((420, "Save"), (590, "Don't Save"), (780, "Cancel")):
        d.rounded_rectangle(
            [x, 470, x + 140, 520], 8, fill=(53, 132, 228) if label == "Save" else (220, 220, 220)
        )
        d.text((x + 20, 482), label, fill=(255, 255, 255) if label == "Save" else (20, 20, 20), font=font(18))  # fmt: skip
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vision(server: LlamaServer) -> dict:
    b64 = base64.b64encode(_dialog_png()).decode()
    t0 = time.monotonic()
    r = server.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {
                        "type": "text",
                        "text": "Read the dialog on this screen. Reply JSON only: "
                        '{"title": ..., "message": ..., "buttons": [...]}',
                    },
                ],
            }
        ],
        max_tokens=150,
        response_format={"type": "json_object"},
        **NO_THINK,
    )
    ms = (time.monotonic() - t0) * 1000
    text = r["choices"][0]["message"].get("content") or ""
    low = text.lower()
    checks = ["unsaved changes", "report_final", "save", "don't save", "cancel"]
    return {
        "latency_ms": round(ms),
        "read_ok": sum(c in low for c in checks) / len(checks),
        "output": text[:300],
    }


# ── runner ───────────────────────────────────────────────────────────────────
def run_model(name: str, tests: list[str], ctx: int, kv: str | None) -> dict:
    spec = MODELS[name]
    path = LLM_DIR / spec["file"]
    if not path.exists():
        return {"model": name, "error": f"missing {path}"}
    result: dict = {
        "model": name,
        "file": spec["file"],
        "ctx": ctx,
        "kv": kv or "f16",
        "at": _now(),
    }
    base_vram = vram_used_mib()
    cfg = ServerConfig(
        model=path, ctx=ctx, kv_type=kv,
        gpu_layers=spec.get("gpu_layers", 99),
        extra=spec.get("extra", []), threads=spec.get("threads"),
    )  # fmt: skip
    log_path = RESULTS / f"server-{name}.log"
    text_tests = [t for t in tests if t != "vision"]
    if text_tests:
        server = LlamaServer(cfg, log_path=log_path)
        with PeakVram() as peak:
            try:
                result["load_s"] = round(server.start(), 1)
                result["vram_loaded_mib"] = vram_used_mib() - base_vram
                server.complete("Warm up the kernels.", n_predict=8)  # JIT + caches
                for t in text_tests:
                    print(f"  {name}: {t} ...", flush=True)
                    result[t] = globals()[f"test_{t}"](server)
            except Exception as e:  # e.g. does not fit in VRAM at this ctx/KV
                result["error"] = str(e)
                return result
            finally:
                server.stop()
        result["vram_peak_mib"] = peak.peak - base_vram

    if "vision" in tests and spec.get("mmproj") and Path(spec["mmproj"]).exists():
        result["vision"] = {}
        for label, offload, max_tok, vctx in VISION_VARIANTS:
            print(f"  {name}: vision ({label}) ...", flush=True)
            vcfg = ServerConfig(
                **{
                    **cfg.__dict__,
                    "ctx": vctx or ctx,
                    "mmproj": spec["mmproj"],
                    "mmproj_offload": offload,
                    "extra": ["--image-max-tokens", str(max_tok)] if max_tok else [],
                }
            )
            slug = label.replace(" ", "").replace(",", "-")
            server = LlamaServer(vcfg, log_path=RESULTS / f"server-{name}-vision-{slug}.log")
            try:
                with PeakVram() as peak:
                    server.start()
                    v = test_vision(server)
                v["vram_peak_mib"] = peak.peak - base_vram
            except Exception as e:  # e.g. out of VRAM with the projector on GPU
                v = {"error": str(e)}
            finally:
                server.stop()
            result["vision"][label] = v
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--models", default="all", help="comma list or 'all'")
    ap.add_argument("-t", "--tests", default=",".join(ALL_TESTS))
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--kv", default=None, help="KV cache type, e.g. q8_0 (default f16)")
    args = ap.parse_args()
    names = list(MODELS) if args.models == "all" else args.models.split(",")
    tests = args.tests.split(",")
    RESULTS.mkdir(exist_ok=True)
    print(f"GPU: {vram_used_mib()} / {vram_total_mib()} MiB used before start")
    for name in names:
        print(f"== {name}", flush=True)
        res = run_model(name, tests, args.ctx, args.kv)
        suffix = f"-{args.kv}" if args.kv else ""
        (RESULTS / f"llm-{name}{suffix}.json").write_text(json.dumps(res, indent=2))
        print(json.dumps({k: v for k, v in res.items() if k not in ("tools", "json")}, indent=1))
        for k in ("tools", "json"):
            if k in res:
                s = res[k]
                print(f"  {k}: tool {s['tool_acc']:.0%} args {s['args_acc']:.0%} "
                      f"valid {s['valid']:.0%} median {s['latency_ms_median']} ms")  # fmt: skip


if __name__ == "__main__":
    main()
