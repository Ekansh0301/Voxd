"""
The Phase 1 voice loop: push-to-talk → speech-to-text → Brain (streamed) →
speech chunks → Kokoro → speaker. Press the key while TARS is talking to cut
it off. State changes are published for the avatar UI.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable

from tars.llm.client import stream_chat
from tars.persona import system_prompt
from tars.sites import SiteRegistry
from tars.voice.audio import Recorder
from tars.voice.chunker import SpeechChunker
from tars.voice.stt import Transcriber
from tars.voice.tts import Speaker

log = logging.getLogger("tars.voice")

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"


class VoiceService:
    def __init__(self, cfg: dict, on_state: Callable[[str, dict], None] | None = None):
        from tars.voice.audio import Player

        self.cfg = cfg
        self.on_state = on_state or (lambda state, info: None)
        vcfg = cfg["voice"]
        log.info("loading speech models…")
        self.stt = Transcriber(vcfg["stt"], hotwords=self._hotwords())
        self.tts = Speaker(vcfg["tts"])
        self.player = Player(self.tts.sample_rate)
        self.recorder = Recorder()
        self.history: list[dict] = []
        self.state = IDLE
        self._turn: asyncio.Task | None = None
        log.info(
            f"ready: STT {vcfg['stt']['model']} on {self.stt.device}, "
            f"TTS {self.tts.engine}/{self.tts.voice}"
        )

    @staticmethod
    def _hotwords() -> list[str]:
        words = ["TARS", "Outlook", "GitHub", "YouTube", "LeetCode", "WhatsApp", "Firefox"]
        return sorted(set(words + SiteRegistry().hotwords()))

    def _set(self, state: str, **info):
        self.state = state
        self.on_state(state, info)

    async def mouth_loop(self, publish: Callable[[dict], None], hz: int = 30):
        """Stream playback loudness to the avatar while speaking (lip-sync)."""
        while True:
            if self.state == SPEAKING:
                publish({"type": "mouth", "v": round(self.player.level, 3)})
            await asyncio.sleep(1 / hz)

    async def run(self, events: AsyncIterator[str]):
        self._set(IDLE)
        async for ev in events:
            if ev == "down":
                await self._interrupt()
                self.recorder.start()
                self._set(LISTENING)
            elif ev == "cancel" and self.recorder.active:
                self.recorder.cancel()
                self._set(IDLE, note="cancelled (shortcut)")
            elif ev == "up" and self.recorder.active:
                audio = self.recorder.stop()
                self._turn = asyncio.create_task(self._guarded_turn(audio, time.monotonic()))

    async def _interrupt(self):
        if self._turn and not self._turn.done():
            self._turn.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._turn
        self.player.interrupt()

    async def _guarded_turn(self, audio, t_release: float):
        try:
            await self._handle_turn(audio, t_release)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # e.g. LLM server down: say so on the avatar, keep running
            log.exception("turn failed")
            self._set("error", note=str(e)[:120])

    async def _handle_turn(self, audio, t_release: float):
        self._set(THINKING)
        text = await asyncio.to_thread(self.stt.transcribe, audio)
        t_stt = time.monotonic()
        if not text:
            self._set(IDLE, note="heard nothing")
            return
        self._set(THINKING, heard=text)
        print(f"\nyou : {text}", flush=True)

        messages = [{"role": "system", "content": system_prompt(self.cfg)}]
        messages += self.history[-2 * self.cfg["llm"].get("history_turns", 8) :]
        messages.append({"role": "user", "content": text})

        chunks: asyncio.Queue[str | None] = asyncio.Queue()
        marks: dict[str, float] = {}
        reply = []

        async def speak():
            while (chunk := await chunks.get()) is not None:
                samples = await asyncio.to_thread(self.tts.synth, chunk)
                if "audio" not in marks:
                    marks["audio"] = time.monotonic()
                    self._set(SPEAKING)
                self.player.enqueue(samples)

        speaker = asyncio.create_task(speak())
        chunker = SpeechChunker()
        try:
            async for delta in stream_chat(
                self.cfg["llm"]["endpoint"], self.cfg["llm"]["brain"], messages,
                max_tokens=400, temperature=0.7, top_p=0.8,
            ):  # fmt: skip
                marks.setdefault("token", time.monotonic())
                reply.append(delta)
                for c in chunker.feed(delta):
                    chunks.put_nowait(c)
            for c in chunker.flush():
                chunks.put_nowait(c)
            chunks.put_nowait(None)
            await speaker
            await asyncio.to_thread(self.player.wait_idle)
        except asyncio.CancelledError:
            speaker.cancel()
            print("tars: (interrupted)", flush=True)
            raise
        finally:
            answer = "".join(reply).strip()
            if answer:
                self.history += [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": answer},
                ]
        print(f"tars: {answer}", flush=True)
        ms = lambda k: round((marks[k] - t_release) * 1000) if k in marks else None  # noqa: E731
        print(
            f"      [stt {round((t_stt - t_release) * 1000)} ms · first token {ms('token')} ms"
            f" · first audio {ms('audio')} ms after you released the key]",
            flush=True,
        )
        self._set(IDLE)
