#!/usr/bin/env python3
"""
plugins/plugin_piper_tts/plugin.py
================================================================================
PyGPT Plugin: Local Piper TTS
================================================================================
Replaces PyGPT's cloud TTS with local Piper TTS.
No API key, no latency, no VRAM usage.

Install:
  1. Copy this entire directory to ~/.config/pygpt-net/plugins/plugin_piper_tts/
  2. Launch PyGPT
  3. Go to Plugins → Manage → Enable "Local Piper TTS"
  4. Configure voices_dir and voice_model in plugin settings

================================================================================
"""

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

# PyGPT plugin base class
try:
    from pygpt_net.core.dispatcher import Event
    from pygpt_net.plugin.base import BasePlugin
except ImportError:
    # Fallback for testing outside PyGPT
    class BasePlugin:
        def __init__(self):
            self.id = ""
            self.name = ""
            self.description = ""
            self.options = {}

        def add_option(self, *args, **kwargs):
            pass

    class Event:
        AUDIO_OUTPUT = "audio_output"


PLUGIN_ID = "plugin_piper_tts"
DEFAULT_VOICES_DIR = str(Path.home() / "flash-copilot" / "voices")
DEFAULT_VOICE = "en_US-ryan-high"


class Plugin(BasePlugin):
    """Local Piper TTS output plugin for PyGPT."""

    def __init__(self):
        super().__init__()
        self.id = PLUGIN_ID
        self.name = "Local Piper TTS"
        self.description = (
            "Replaces cloud TTS with local Piper neural TTS. " "Fast, private, no API key needed."
        )
        self.order = 100
        self._tts_lock = threading.Lock()

        # Register options (shown in PyGPT settings UI)
        self.add_option(
            "voices_dir",
            type="path",
            value=DEFAULT_VOICES_DIR,
            label="Voices directory",
            description="Directory containing .onnx voice model files",
        )
        self.add_option(
            "voice_model",
            type="text",
            value=DEFAULT_VOICE,
            label="Voice model name",
            description="Name of voice (e.g. en_US-ryan-high, en_US-lessac-medium)",
        )
        self.add_option(
            "speed",
            type="float",
            value=0.95,
            label="Speech speed",
            description="1.0 = normal, 0.9 = slightly faster, 1.2 = slower",
            min=0.5,
            max=2.0,
        )
        self.add_option(
            "enabled",
            type="bool",
            value=True,
            label="Enable Piper TTS",
            description="Use local Piper instead of cloud TTS",
        )

    def setup(self) -> dict:
        """Return option definitions."""
        return self.options

    def attach(self, window):
        """Called when plugin is attached to PyGPT window."""
        self.window = window

    def handle(self, event: Event, *args, **kwargs):
        """Handle PyGPT events."""
        name = event.name

        if name == Event.AUDIO_OUTPUT:
            # Intercept audio output — speak with Piper instead
            if self.get_option_value("enabled"):
                text = event.data.get("text", "")
                if text:
                    threading.Thread(target=self._speak, args=(text,), daemon=True).start()
                    # Signal that we handled audio output
                    event.stop = True

    def _speak(self, text: str):
        """Synthesize and play speech."""
        with self._tts_lock:
            voices_dir = Path(self.get_option_value("voices_dir"))
            voice_model = self.get_option_value("voice_model")
            speed = float(self.get_option_value("speed"))

            voice_path = voices_dir / f"{voice_model}.onnx"

            if not voice_path.exists():
                print(f"[PiperTTS] Voice not found: {voice_path}")
                print("[PiperTTS] Run install.sh to download voices.")
                return

            clean_text = self._clean(text)
            if not clean_text:
                return

            self._piper_speak(clean_text, str(voice_path), speed)

    def _piper_speak(self, text: str, model_path: str, speed: float):
        """Run Piper and play the audio."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        tmp_path = tmp.name

        try:
            # Try Python module first
            proc = subprocess.run(
                [
                    "python3",
                    "-m",
                    "piper",
                    "--model",
                    model_path,
                    "--output_file",
                    tmp_path,
                    "--length_scale",
                    str(round(1.0 / speed, 2)),
                    "--noise_scale",
                    "0.667",
                    "--noise_w",
                    "0.8",
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )

            if proc.returncode != 0:
                # Try CLI version
                proc2 = subprocess.run(
                    ["piper", "--model", model_path, "--output_file", tmp_path],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=30,
                )
                if proc2.returncode != 0:
                    print("[PiperTTS] Both piper methods failed")
                    return

            # Play the WAV
            self._play(tmp_path)

        except subprocess.TimeoutExpired:
            print("[PiperTTS] TTS timed out")
        except Exception as e:
            print(f"[PiperTTS] Error: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _play(self, wav_path: str):
        """Play WAV via aplay (ALSA) or paplay (PulseAudio)."""
        for player in ["paplay", "aplay", "play"]:
            result = subprocess.run(["which", player], capture_output=True)
            if result.returncode == 0:
                subprocess.run([player, wav_path], capture_output=True, timeout=60)
                return
        print("[PiperTTS] No audio player found (need aplay, paplay, or play)")

    def _clean(self, text: str) -> str:
        """Remove markdown for clean TTS."""
        text = re.sub(r"```[\s\S]*?```", "code block", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-•*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"https?://\S+", "link", text)
        text = re.sub(r"\n+", " ", text)
        text = re.sub(r"\s+", " ", text)
        if len(text) > 600:
            text = text[:597] + "..."
        return text.strip()

    def get_option_value(self, key: str):
        """Get option value with fallback to default."""
        opt = self.options.get(key, {})
        return opt.get("value", opt.get("default", ""))
