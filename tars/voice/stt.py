"""Speech-to-text with faster-whisper on the CPU (keeps the GPU for the Brain)."""

import numpy as np

from tars import MODELS_DIR

MIN_SECONDS = 0.35


class Transcriber:
    def __init__(self, cfg: dict, hotwords: list[str] | None = None):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            str(MODELS_DIR / "stt" / cfg.get("model", "small.en")),
            device=cfg.get("device", "cpu"),
            compute_type=cfg.get("compute_type", "int8"),
            cpu_threads=cfg.get("threads", 6),
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
