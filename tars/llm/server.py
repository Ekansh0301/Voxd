"""
Start/stop a llama.cpp `llama-server` process and talk to it.

Used by the benchmarks (bench/); at run time TARS goes through llama-swap (tars/llm/swap.py). Only the
native endpoints we rely on are wrapped: /health, /tokenize, /completion and
the OpenAI-compatible /v1/chat/completions (which llama-server extends with a
`timings` object).
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from tars import BIN_DIR

log = logging.getLogger("tars.llm.server")


@dataclass
class ServerConfig:
    model: Path
    port: int = 8091
    ctx: int = 8192
    gpu_layers: int = 99  # 0 = CPU only
    parallel: int = 1
    threads: Optional[int] = None
    kv_type: Optional[str] = None  # e.g. "q8_0" for both K and V
    flash_attn: str = "auto"
    mmproj: Optional[Path] = None
    mmproj_offload: bool = True
    extra: list[str] = field(default_factory=list)

    def argv(self) -> list[str]:
        a = [
            str(BIN_DIR / "llama-server"),
            "-m", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-c", str(self.ctx),
            "-ngl", str(self.gpu_layers),
            "-np", str(self.parallel),
            "-fa", self.flash_attn,
            "-fit", "off",  # fail loudly instead of silently shrinking ctx/layers
            "--jinja",
            "--no-webui",
            "--metrics",
        ]  # fmt: skip
        if self.threads:
            a += ["-t", str(self.threads)]
        if self.kv_type:
            a += ["-ctk", self.kv_type, "-ctv", self.kv_type]
        if self.mmproj:
            a += ["--mmproj", str(self.mmproj)]
            if not self.mmproj_offload:
                a.append("--no-mmproj-offload")
        return a + self.extra


class LlamaServer:
    def __init__(self, cfg: ServerConfig, log_path: Optional[Path] = None):
        self.cfg = cfg
        self.base = f"http://127.0.0.1:{cfg.port}"
        self.log_path = log_path
        self.proc: Optional[subprocess.Popen] = None
        self.http = httpx.Client(base_url=self.base, timeout=300)

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self, timeout: float = 180) -> float:
        """Launch and wait until the model is loaded. Returns load seconds."""
        out = open(self.log_path, "w") if self.log_path else subprocess.DEVNULL
        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            self.cfg.argv(),
            stdout=out,
            stderr=subprocess.STDOUT,
            # The GTX 16xx build JIT-compiles PTX kernels on first use; a big cache
            # keeps them across restarts so only the very first launch pays for it.
            env={"CUDA_CACHE_MAXSIZE": str(4 << 30), **os.environ},
        )
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited with {self.proc.returncode}"
                    + (f" (see {self.log_path})" if self.log_path else "")
                )
            try:
                if self.http.get("/health", timeout=2).status_code == 200:
                    return time.monotonic() - t0
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        self.stop()
        raise TimeoutError("llama-server did not become healthy")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # ── endpoints ─────────────────────────────────────────────────────────
    def tokenize(self, text: str) -> list[int]:
        r = self.http.post("/tokenize", json={"content": text})
        r.raise_for_status()
        return r.json()["tokens"]  # type: ignore[no-any-return]

    def complete(self, prompt: Any, n_predict: int = 64, **kw) -> dict:
        body = {
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": 0.0,
            "cache_prompt": True,
            **kw,
        }
        r = self.http.post("/completion", json=body)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]

    def chat(self, messages: list[dict], **kw) -> dict:
        body = {"messages": messages, "temperature": 0.0, "cache_prompt": True, **kw}
        r = self.http.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]
