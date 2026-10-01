"""Microphone capture and interruptible playback (sounddevice / PipeWire)."""

import collections
import threading

import numpy as np
import sounddevice as sd

MIC_RATE = 16000  # what Whisper wants


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def start(self):
        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=MIC_RATE, channels=1, dtype="float32", callback=self._cb, blocksize=512
        )
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        self._chunks.append(indata[:, 0].copy())

    def _close(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def stop(self) -> np.ndarray:
        self._close()
        return np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)

    def cancel(self):
        self._close()
        self._chunks = []

    @property
    def active(self) -> bool:
        return self._stream is not None


class Player:
    """
    Streams queued sample buffers to the speaker from one output stream, so
    consecutive TTS chunks play back to back. interrupt() silences it at once.
    `level` (0..1) tracks loudness of what is playing, for avatar lip-sync.
    """

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate
        self._queue: collections.deque[np.ndarray] = collections.deque()
        self._pos = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self.level = 0.0
        self._stream = sd.OutputStream(
            samplerate=sample_rate, channels=1, dtype="float32", callback=self._cb, blocksize=480
        )
        self._stream.start()

    def _cb(self, outdata, frames, t, status):
        out = outdata[:, 0]
        filled = 0
        with self._lock:
            while filled < frames and self._queue:
                buf = self._queue[0]
                take = min(frames - filled, len(buf) - self._pos)
                out[filled : filled + take] = buf[self._pos : self._pos + take]
                filled += take
                self._pos += take
                if self._pos >= len(buf):
                    self._queue.popleft()
                    self._pos = 0
            if not self._queue and filled < frames:
                self._idle.set()
        out[filled:] = 0
        self.level = float(min(1.0, np.sqrt(np.mean(out**2)) * 4)) if frames else 0.0

    def enqueue(self, samples: np.ndarray):
        if len(samples):
            with self._lock:
                self._queue.append(samples)
                self._idle.clear()

    def interrupt(self):
        with self._lock:
            self._queue.clear()
            self._pos = 0
            self._idle.set()
        self.level = 0.0

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    @property
    def playing(self) -> bool:
        return not self._idle.is_set()

    def close(self):
        self._stream.stop()
        self._stream.close()
