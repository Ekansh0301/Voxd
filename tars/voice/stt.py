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
        self._path, self._threads = path, cfg.get("threads", 6)
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
            self._to_cpu()
        self.hotwords = ", ".join(hotwords) if hotwords else None
        self.transcribe(np.zeros(16000, np.float32))  # warm-up

    def _to_cpu(self):
        from faster_whisper import WhisperModel

        self.device = "cpu"
        self.model = WhisperModel(
            self._path, device="cpu", compute_type="int8", cpu_threads=self._threads
        )

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < MIN_SECONDS * 16000:
            return ""
        try:
            return self._transcribe(audio)
        except RuntimeError as e:
            # A CUDA error (e.g. out of memory) can leave the context unusable, so
            # stay on the CPU for the rest of the session rather than fail every turn.
            if self.device == "cpu":
                raise
            log.warning(f"Whisper GPU error ({e}); switching to the CPU for this session")
            self._to_cpu()
            return self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,  # drops silence; push-to-talk clips often start/end quiet
            temperature=0.0,  # no retries at higher temperatures (best_of=5 needs extra VRAM)
            condition_on_previous_text=False,
            without_timestamps=True,
            hotwords=self.hotwords,
        )
        return " ".join(s.text.strip() for s in segments).strip()
