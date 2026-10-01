"""Speech-to-text with faster-whisper: on the GPU next to the Brain (~0.5 s), CPU fallback."""

import logging

import numpy as np

from tars import MODELS_DIR

log = logging.getLogger("tars.stt")
MIN_SECONDS = 0.35


class Transcriber:
    def __init__(self, cfg: dict, hotwords: list[str] | None = None):
        from faster_whisper import WhisperModel

        path = str(MODELS_DIR / "stt" / cfg.get("model", "small.en"))
        self.device = cfg.get("device", "cpu")
        try:
            self.model = WhisperModel(
                path,
                device=self.device,
                compute_type=cfg.get("compute_type", "int8"),
                cpu_threads=cfg.get("threads", 6),
            )
            if self.device == "cuda":
                self.model.transcribe(np.zeros(16000, np.float32))  # fails here if no cuDNN/VRAM
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning(f"Whisper on {self.device} failed ({e}); using the CPU (slower)")
            self.device = "cpu"
            self.model = WhisperModel(
                path, device="cpu", compute_type="int8", cpu_threads=cfg.get("threads", 6)
            )
        self.hotwords = ", ".join(hotwords) if hotwords else None
        self.transcribe(np.zeros(16000, np.float32))  # warm-up

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < MIN_SECONDS * 16000:
            return ""
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,  # drops silence; push-to-talk clips often start/end quiet
            condition_on_previous_text=False,
            without_timestamps=True,
            hotwords=self.hotwords,
        )
        return " ".join(s.text.strip() for s in segments).strip()
