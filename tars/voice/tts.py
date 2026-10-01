"""Text-to-speech: Kokoro (default voice af_heart) with Piper as the fallback."""

import logging

import numpy as np

from tars import MODELS_DIR

log = logging.getLogger("tars.tts")
TTS_DIR = MODELS_DIR / "tts"


class Speaker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine = cfg.get("engine", "kokoro")
        if self.engine == "kokoro":
            try:
                self._load_kokoro()
                return
            except Exception as e:  # missing model / broken install: still talk
                log.warning(f"Kokoro unavailable ({e}); falling back to Piper")
                self.engine = "piper"
        self._load_piper()

    def _load_kokoro(self):
        from kokoro_onnx import Kokoro

        self._kokoro = Kokoro(
            str(TTS_DIR / self.cfg.get("kokoro_model", "kokoro-v1.0.onnx")),
            str(TTS_DIR / "voices-v1.0.bin"),
        )
        self.voice = self.cfg.get("voice", "af_heart")
        self.lang = "en-gb" if self.voice.startswith("b") else "en-us"
        self.sample_rate = 24000
        self.synth("Ready.")  # warm-up: the first call is several times slower

    def _load_piper(self):
        from piper import PiperVoice

        name = self.cfg.get("piper_voice", "en_US-lessac-medium")
        self._piper = PiperVoice.load(str(TTS_DIR / "piper" / f"{name}.onnx"))
        self.voice = name
        self.sample_rate = self._piper.config.sample_rate

    def synth(self, text: str) -> np.ndarray:
        """Mono float32 samples at self.sample_rate."""
        if self.engine == "kokoro":
            samples, _ = self._kokoro.create(
                text, voice=self.voice, speed=self.cfg.get("speed", 1.0), lang=self.lang
            )
            return np.asarray(samples, dtype=np.float32)
        parts = [c.audio_float_array for c in self._piper.synthesize(text)]
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)
