"""
core/gpu_lock.py — Process-wide GPU resource mutex.

Why this exists:
  The main voice loop (record -> Whisper STT -> Ollama LLM -> Piper TTS) is
  naturally sequential, so it never actually contends with itself. The real
  concurrency risk is the ProactiveMonitor background thread (core/monitor.py),
  which can fire at any time on its own timer and may need to speak an alert
  (TTS) or, in future, ask the LLM to phrase that alert — while the main
  thread is potentially still transcribing or generating a response on the
  same 4GB GPU.

  Without coordination, two GPU-bound calls landing at the same instant can
  cause CUDA OOM errors or silent memory thrashing on a constrained card.

  GPU_LOCK is a single, process-wide lock that any GPU-touching call
  (Whisper transcription, Ollama inference) acquires before running. It is
  intentionally NOT held during TTS playback (Piper runs on CPU and does
  not touch VRAM), so normal voice interaction latency is unaffected.

Usage:
  from core.gpu_lock import GPU_LOCK

  with GPU_LOCK:
      segments, _ = whisper_model.transcribe(audio, ...)

  with GPU_LOCK:
      response = requests.post(OLLAMA_URL, json=payload, ...)
"""

import logging
import threading
import time

log = logging.getLogger('flash.gpu_lock')


class GPUResourceLock:
    """
    A re-entrant, instrumented mutex around GPU-bound work.

    Re-entrant (RLock) because a single call path may legitimately need to
    acquire it twice on the same thread (e.g. the LLM call inside
    Brain._maybe_summarise() running while already inside Brain._llm()'s
    lock during a synthesize step). A plain Lock would deadlock that case;
    RLock allows the owning thread to re-acquire safely.
    """

    def __init__(self, name: str = "gpu"):
        self._lock = threading.RLock()
        self._name = name
        self._holder = None
        self._wait_warn_after = 5.0  # seconds — log if a caller waits this long

    def __enter__(self):
        start = time.monotonic()
        acquired = self._lock.acquire(timeout=30)
        waited = time.monotonic() - start

        if not acquired:
            log.error(
                f"[{self._name}] lock acquire TIMED OUT after 30s "
                f"(held by: {self._holder})"
            )
            # Force-acquire anyway rather than hang the assistant forever —
            # this trades a possible CUDA contention error for guaranteed
            # liveness, which is the right tradeoff for a desktop assistant.
            self._lock.acquire()

        elif waited > self._wait_warn_after:
            log.warning(
                f"[{self._name}] waited {waited:.1f}s for GPU lock "
                f"(thread: {threading.current_thread().name})"
            )

        self._holder = threading.current_thread().name
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._holder = None
        self._lock.release()
        return False  # don't suppress exceptions


# Single process-wide instance. Import this, don't instantiate your own —
# the whole point is that every GPU-touching call shares the same lock.
GPU_LOCK = GPUResourceLock(name="gpu")