"""
core/voice_engine.py — STT + TTS  (v4 — bug fixes)

Fixed vs v3:
  - Removed initial_prompt (was being hallucinated as transcription output)
  - 300ms post-interrupt delay prevents TTS audio bleed into mic
  - Piper process killed directly on interrupt (no lock deadlock)
  - VAD threshold lowered further for Indian English
  - Audio device released cleanly between interrupt and record
"""

import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from gpu_lock import GPU_LOCK

log = logging.getLogger('flash.voice')

SAMPLE_RATE = 16000
CHANNELS    = 1
DTYPE       = 'float32'


class VoiceEngine:
    def __init__(self, voices_dir: Path, voice_model: str = 'en_US-ryan-high'):
        self.voices_dir     = Path(voices_dir)
        self.voice_model    = voice_model
        self._recording     = False
        self._audio_buf     = []
        self._stream        = None
        self._whisper       = None
        self._stt_lock      = threading.Lock()
        self._tts_lock      = threading.Lock()
        self._stop_speaking = False
        self._piper_proc    = None   # track piper process for hard kill

        # Locate piper binary
        project_dir = Path(__file__).parent.parent
        binary = project_dir / 'piper_bin' / 'piper'
        self._piper_bin = str(binary) if binary.exists() else 'piper'
        log.info(f"Piper binary: {self._piper_bin}")

        self._load_whisper()

    # ── Whisper ───────────────────────────────────────────────────────────────

    def _load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            import torch
            device  = 'cuda' if torch.cuda.is_available() else 'cpu'
            compute = 'float16' if device == 'cuda' else 'int8'
            log.info(f"Loading Whisper Small on {device}/{compute}...")
            self._whisper = WhisperModel('small', device=device,
                                         compute_type=compute)
            log.info("Whisper Small loaded.")
        except Exception as e:
            log.error(f"Whisper load failed: {e}")
            self._whisper = None

    def start_recording(self):
        self._audio_buf = []
        self._recording = True

        def _cb(indata, frames, t, status):
            if self._recording:
                self._audio_buf.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype=DTYPE, callback=_cb, blocksize=1024)
            self._stream.start()
        except Exception as e:
            log.error(f"Recording start failed: {e}")
            self._recording = False

    def stop_recording(self) -> Optional[np.ndarray]:
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if not self._audio_buf:
            return None

        audio = np.concatenate(self._audio_buf).flatten()
        audio = self._trim_silence(audio)
        log.info(f"Recorded {len(audio)/SAMPLE_RATE:.2f}s of audio")
        return audio

    def _trim_silence(self, audio: np.ndarray,
                      threshold: float = 0.006) -> np.ndarray:
        nonsilent = np.where(np.abs(audio) > threshold)[0]
        if len(nonsilent) == 0:
            return audio
        s = max(0, nonsilent[0]  - 3200)
        e = min(len(audio), nonsilent[-1] + 3200)
        return audio[s:e]

    def transcribe(self, audio: np.ndarray) -> str:
        if self._whisper is None or audio is None:
            return ""
        if len(audio) < SAMPLE_RATE * 0.25:
            return ""

        with self._stt_lock:
            try:
                with GPU_LOCK: 
                    segments, _ = self._whisper.transcribe(
                        audio,
                        beam_size=3,
                        language='en',
                        # NO initial_prompt — it was being hallucinated as output
                        vad_filter=True,
                        vad_parameters={
                            'min_silence_duration_ms': 500,
                            'threshold': 0.12,       # very sensitive
                            'speech_pad_ms': 500,
                            'min_speech_duration_ms': 80,
                        },
                        condition_on_previous_text=False,
                        temperature=0.0,             # deterministic, no hallucination
                    )
                text = ' '.join(s.text for s in segments).strip()
                # Strip Whisper artifacts
                text = re.sub(r'\[.*?\]', '', text).strip()
                text = re.sub(r'\(.*?\)', '', text).strip()
                # Reject if output is suspiciously long for the audio duration
                max_words = int(len(audio) / SAMPLE_RATE * 5)  # ~5 words/sec
                if len(text.split()) > max_words + 8:
                    log.warning(f"Hallucination detected, rejecting: {text[:60]}")
                    return ""
                log.info(f"Transcribed: '{text}'")
                return text
            except Exception as e:
                log.error(f"Transcription error: {e}")
                return ""

    # ── TTS ───────────────────────────────────────────────────────────────────

    def interrupt(self):
        """Stop TTS immediately. Kills piper process, releases audio."""
        self._stop_speaking = True
        # Hard-kill piper if it's generating
        if self._piper_proc and self._piper_proc.poll() is None:
            try:
                self._piper_proc.kill()
            except Exception:
                pass
            self._piper_proc = None
        # Stop sounddevice
        try:
            sd.stop()
        except Exception:
            pass
        log.info("TTS interrupted")
        # Wait for audio device to fully release
        time.sleep(0.3)

    def speak(self, text: str):
        if not text or not text.strip():
            return
        self._stop_speaking = False
        clean = self._clean_for_speech(text)
        if not clean:
            return
        # Non-blocking lock attempt — if already speaking, skip
        acquired = self._tts_lock.acquire(timeout=0.5)
        if not acquired:
            return
        try:
            if self._stop_speaking:
                return
            self._piper_speak(clean)
        finally:
            self._tts_lock.release()

    def _piper_speak(self, text: str):
        # Find voice
        voice_path = self.voices_dir / f"{self.voice_model}.onnx"
        if not voice_path.exists():
            for fb in ['en_US-ryan-high', 'en_US-lessac-high',
                       'en_US-lessac-medium', 'en_US-amy-medium']:
                fp = self.voices_dir / f"{fb}.onnx"
                if fp.exists():
                    voice_path = fp
                    log.warning(f"Voice fallback: {fb}")
                    break
            else:
                subprocess.run(['espeak-ng', '-s', '145', text],
                               capture_output=True)
                return

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
                tmp_path = t.name

            # Run piper — track process for hard kill
            self._piper_proc = subprocess.Popen(
                [self._piper_bin,
                 '--model',        str(voice_path),
                 '--output_file',  tmp_path,
                 '--length_scale', '1.0',
                 '--noise_scale',  '0.667',
                 '--noise_w',      '0.8'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            _, stderr = self._piper_proc.communicate(
                input=text.encode('utf-8'), timeout=20)
            rc = self._piper_proc.returncode
            self._piper_proc = None

            if rc != 0:
                log.error(f"Piper error: {stderr.decode()[:150]}")
                subprocess.run(['espeak-ng', '-s', '145', text],
                               capture_output=True)
                return

            if self._stop_speaking:
                return

            self._play_interruptible(tmp_path)

        except subprocess.TimeoutExpired:
            if self._piper_proc:
                self._piper_proc.kill()
                self._piper_proc = None
            log.error("Piper timed out")
        except FileNotFoundError:
            log.error(f"Piper not found: {self._piper_bin}")
            subprocess.run(['espeak-ng', '-s', '145', text],
                           capture_output=True)
        except Exception as e:
            log.error(f"Piper error: {e}")
        finally:
            if tmp_path:
                try: os.unlink(tmp_path)
                except Exception: pass

    def _play_interruptible(self, path: str):
        try:
            data, sr = sf.read(path, dtype='float32')
            # Normalize to prevent clipping
            peak = abs(data).max()
            if peak > 0.85: data = data * (0.85 / peak)
            chunk_size = int(sr * 0.30)
            for i in range(0, len(data), chunk_size):
                if self._stop_speaking:
                    sd.stop()
                    return
                sd.play(data[i:i+chunk_size], sr)
                sd.wait()
        except Exception as e:
            log.error(f"Playback error: {e}")
            try:
                subprocess.run(['aplay', path], capture_output=True,
                               timeout=30)
            except Exception:
                pass

    def _clean_for_speech(self, text: str) -> str:
        text = re.sub(r'```[\s\S]*?```', 'code block', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-•*]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'https?://\S+', 'link', text)
        text = re.sub(r'^TOOL_CALL:.*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:500] if len(text) > 500 else text

    def set_voice(self, model: str):
        self.voice_model = model
        log.info(f"Voice: {model}")