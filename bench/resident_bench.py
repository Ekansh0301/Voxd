"""
Resident-setup benchmark: the Brain (GPU) and the Scout (CPU) running at the
same time, as llama-swap serves them. Finds the Brain slot count and Scout
thread count that keep the Brain fast while the Scout works.

    .venv/bin/python -m bench.resident_bench
"""

import base64
import concurrent.futures as cf
import json
import time
from pathlib import Path

from bench.llm_bench import MMPROJ_4B, _dialog_png
from tars import MODELS_DIR
from tars.gpu import vram_used_mib
from tars.llm.server import LlamaServer, ServerConfig

RESULTS = Path(__file__).parent / "results"
LLM = MODELS_DIR / "llm"
NT = {"chat_template_kwargs": {"enable_thinking": False}}
LONG_Q = "Explain in about 120 words how a mutex differs from a semaphore."
SCOUT_Q = "Summarise this email in two lines: " + (
    "Hi all, the professor has moved Thursday's lab to Friday at 10 am because of the fest. "
    "Please bring your laptops with the assignment environment set up, and submit the "
    "pre-lab quiz by Thursday night. Late submissions will not be accepted. " * 4
)


def brain_cfg(parallel: int) -> ServerConfig:
    return ServerConfig(
        model=LLM / "Qwen3.5-4B-Q4_K_M.gguf", port=8095, ctx=8192, parallel=parallel,
        mmproj=MMPROJ_4B, mmproj_offload=False,
        extra=["--image-max-tokens", "256", "--cache-reuse", "256"],
    )  # fmt: skip


def scout_cfg(threads: int) -> ServerConfig:
    return ServerConfig(
        model=LLM / "Qwen3.5-0.8B-Q4_K_M.gguf", port=8096, ctx=8192, gpu_layers=0,
        threads=threads, extra=["--device", "none"],
    )  # fmt: skip


def gen(server: LlamaServer, text: str, n: int = 150) -> dict:
    r = server.chat([{"role": "user", "content": text}], max_tokens=n, **NT)
    t = r.get("timings", {})
    return {
        "decode_tps": round(t.get("predicted_per_second", 0), 1),
        "tokens": t.get("predicted_n"),
    }


def vision(server: LlamaServer) -> float:
    b64 = base64.b64encode(_dialog_png()).decode()
    t = time.monotonic()
    server.chat(
        [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": "What does this dialog ask? One line."}]}],
        max_tokens=60, **NT,
    )  # fmt: skip
    return round(time.monotonic() - t, 1)


def main():
    out = []
    base = vram_used_mib()
    for parallel in (1, 2):
        brain = LlamaServer(
            brain_cfg(parallel), log_path=RESULTS / f"server-resident-np{parallel}.log"
        )
        brain.start()
        brain.complete("warm up", n_predict=8)
        row: dict = {"brain_slots": parallel, "vram_mib": vram_used_mib() - base}
        row["brain_alone"] = gen(brain, LONG_Q)
        row["vision_alone_s"] = vision(brain)
        row["vram_after_requests_mib"] = vram_used_mib() - base
        for threads in (6, 4, 3):
            scout = LlamaServer(
                scout_cfg(threads), log_path=RESULTS / f"server-scout-t{threads}.log"
            )
            scout.start()
            gen(scout, "warm up", 8)
            with cf.ThreadPoolExecutor(2) as ex:
                fb = ex.submit(gen, brain, LONG_Q)
                fs = ex.submit(gen, scout, SCOUT_Q, 80)
                row[f"together_scout_t{threads}"] = {"brain": fb.result(), "scout": fs.result()}
            with cf.ThreadPoolExecutor(2) as ex:
                fv = ex.submit(vision, brain)
                fs = ex.submit(gen, scout, SCOUT_Q, 80)
                row[f"vision_with_scout_t{threads}_s"] = fv.result()
                fs.result()
            scout.stop()
        brain.stop()
        print(json.dumps(row), flush=True)
        out.append(row)
    (RESULTS / "resident.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
