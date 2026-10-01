"""
The voice loop: push-to-talk → speech-to-text → agent (Brain + tools, streamed)
→ speech chunks → Kokoro → speaker. Press the key while TARS is talking to cut
it off. Actions that need approval are asked out loud; your next push-to-talk
answer is the yes/no. State changes are published for the avatar UI.
"""

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from tars import router
from tars.agent.loop import run_turn
from tars.agent.tools import Context, Registry
from tars.memory.store import Memory
from tars.persona import stamp, system_prompt
from tars.sites import SiteRegistry
from tars.tools import default_registry
from tars.voice import commands
from tars.voice.audio import Recorder
from tars.voice.chunker import SpeechChunker
from tars.voice.stt import Transcriber
from tars.voice.tts import Speaker

log = logging.getLogger("tars.voice")

IDLE, LISTENING, THINKING, SPEAKING, CONFIRMING = (
    "idle", "listening", "thinking", "speaking", "confirming",
)  # fmt: skip
APPROVAL_TIMEOUT = 30
NARRATION = {"get_system_info": "Checking.", "find_files": "Searching.", "run_command": "On it."}


def speakable(summary: str) -> str:
    """'run `mkdir x` (mkdir may change things)' -> 'run mkdir x'; ~/A/b.txt -> b.txt in A."""
    s = re.sub(r"\s*\([^)]*\)$", "", summary).replace("`", "")
    s = re.sub(r"~/((?:[^/\s]+/)*)([^/\s]+)", lambda m: m.group(2) + (f" in {m.group(1).rstrip('/').split('/')[-1]}" if m.group(1) else " in your home folder"), s)  # fmt: skip
    return s


class VoiceService:
    def __init__(
        self,
        cfg: dict,
        on_state: Callable[[str, dict], None] | None = None,
        save_audio: Path | None = None,
        memory: Memory | None = None,
        registry: Registry | None = None,
    ):
        from tars.voice.audio import Player

        self.cfg = cfg
        self.on_state = on_state or (lambda state, info: None)
        vcfg = cfg["voice"]
        log.info("loading speech models…")
        self.stt = Transcriber(vcfg["stt"], hotwords=vcfg["stt"].get("hotwords"))
        self.tts = Speaker(vcfg["tts"])
        self.player = Player(self.tts.sample_rate)
        self.recorder = Recorder()
        self.memory = memory or Memory()
        self.registry = registry or default_registry(self.memory)
        self.sites = SiteRegistry()
        self.site_names = [
            s.key.capitalize() for s in self.sites.sites.values() if s.access != "blocked"
        ]
        self.ctx = Context(
            sites=self.sites, approve=self._approve, desktop=True, notify=self._announce
        )
        self.history: list[dict] = []
        self.save_audio = save_audio  # opt-in: keep your utterances for STT evaluation
        if save_audio:
            save_audio.mkdir(parents=True, exist_ok=True)
        self.state = IDLE
        self._turn: asyncio.Task | None = None
        self._approval: asyncio.Future[str] | None = None
        log.info(
            f"ready: STT {vcfg['stt']['model']} on {self.stt.device}, "
            f"TTS {self.tts.engine}/{self.tts.voice}, {len(self.registry.tools)} tools"
        )

    def _set(self, state: str, **info):
        self.state = state
        self.on_state(state, info)

    async def mouth_loop(self, publish: Callable[[dict], None], hz: int = 30):
        """Stream playback loudness to the avatar while speaking (lip-sync)."""
        while True:
            if self.state in (SPEAKING, CONFIRMING):
                publish({"type": "mouth", "v": round(self.player.level, 3)})
            await asyncio.sleep(1 / hz)

    # ── push-to-talk events ─────────────────────────────────────────────────
    async def run(self, events: AsyncIterator[str]):
        self._set(IDLE)
        async for ev in events:
            awaiting_answer = self._approval is not None and not self._approval.done()
            if ev == "down":
                if awaiting_answer:
                    self.player.interrupt()  # stop the question, keep the turn waiting
                else:
                    await self._interrupt()
                self.recorder.start()
                self._set(LISTENING)
            elif ev == "cancel" and self.recorder.active:
                self.recorder.cancel()
                self._set(CONFIRMING if awaiting_answer else IDLE, note="cancelled (shortcut)")
            elif ev == "up" and self.recorder.active:
                audio = self.recorder.stop()
                if awaiting_answer:
                    asyncio.create_task(self._answer_approval(audio))
                else:
                    self._turn = asyncio.create_task(self._guarded_turn(audio, time.monotonic()))

    async def _interrupt(self):
        if self._turn and not self._turn.done():
            self._turn.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._turn
        self.player.interrupt()

    # ── speaking outside a streamed answer ──────────────────────────────────
    async def _say(self, text: str, state: str = SPEAKING):
        samples = await asyncio.to_thread(self.tts.synth, text)
        self._set(state)
        self.player.enqueue(samples)
        await asyncio.to_thread(self.player.wait_idle)

    def _announce(self, message: str):
        """Timers and other background events speak up when TARS is free."""

        async def when_free():
            while self.state not in (IDLE,) or self.recorder.active:
                await asyncio.sleep(0.5)
            print(f"tars: {message}", flush=True)
            await self._say(message)
            self._set(IDLE)

        asyncio.get_running_loop().create_task(when_free())

    # ── approvals ───────────────────────────────────────────────────────────
    async def _approve(self, summary: str) -> bool:
        print(f"      [asks: {summary}]", flush=True)
        await asyncio.to_thread(self.player.wait_idle)  # let narration finish
        self._approval = asyncio.get_running_loop().create_future()
        await self._say(f"Should I {speakable(summary)}? Say yes or no.", state=CONFIRMING)
        self._set(CONFIRMING, note=summary)
        try:
            answer = await asyncio.wait_for(self._approval, APPROVAL_TIMEOUT)
        except TimeoutError:
            answer = ""
        finally:
            self._approval = None
        ok = commands.parse_yes_no(answer) is True
        print(f"      [{'approved' if ok else 'declined'}]", flush=True)
        self._set(THINKING)
        return ok

    async def _answer_approval(self, audio):
        self._set(THINKING)
        text = await asyncio.to_thread(self.stt.transcribe, audio)
        print(f"you : {text}", flush=True)
        if self._approval is not None and not self._approval.done():
            self._approval.set_result(text)

    # ── one turn ────────────────────────────────────────────────────────────
    def _save(self, audio, text: str):
        import json

        import soundfile as sf

        assert self.save_audio is not None
        name = time.strftime("%Y%m%d-%H%M%S")
        sf.write(self.save_audio / f"{name}.wav", audio, 16000)
        with (self.save_audio / "manifest.jsonl").open("a") as f:
            f.write(json.dumps({"file": f"{name}.wav", "heard": text, "text": text}) + "\n")

    async def _guarded_turn(self, audio, t_release: float):
        try:
            await self._handle_turn(audio, t_release)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # e.g. LLM server down: say so on the avatar, keep running
            log.exception("turn failed")
            self._set("error", note=str(e)[:120])

    async def _fast_path(self, text: str, route: "router.Route", stt_s: float) -> bool:
        """Run an unambiguous command without the LLM. False = let the agent handle it."""
        t0 = time.monotonic()
        speaking = asyncio.create_task(self._say(route.ack)) if route.ack else None
        result = await self.registry.call(self.ctx, route.tool, route.args)
        if speaking:
            await speaking
        if result.startswith(("error", "refused")):
            log.info(f"fast path {route.tool} failed ({result}); asking the agent")
            return False
        reply = route.ack
        if route.tool == "get_datetime":  # "Wednesday 01 October 2026, 10:42 AM IST"
            day, _, clock = result.partition(", ")
            reply = f"It's {clock.rsplit(' ', 1)[0].lstrip('0')}, {day.split()[0]}."
            await self._say(reply)
        print(f"      · {route.tool}({route.args}) [fast path]\ntars: {reply}", flush=True)
        print(
            f"      [stt {round(stt_s * 1000)} ms · done {round((time.monotonic() - t0) * 1000)} ms later]",
            flush=True,
        )
        self.history += [
            {"role": "user", "content": text},
            {
                "role": "assistant",
                "content": f"{reply}\n[done: {route.tool}({route.args}) -> {result[:80]}]",
            },
        ]
        self._set(IDLE)
        return True

    def _narration(self, name: str, args: dict) -> str | None:
        if name in ("open_url", "open_app"):
            target = args.get("url") or args.get("name") or ""
            site = self.sites.resolve(target) or self.sites.site_for_url(target)
            return f"Opening {site.key.capitalize() if site else target}."
        return NARRATION.get(name)

    async def _handle_turn(self, audio, t_release: float):
        self._set(THINKING)
        text = await asyncio.to_thread(self.stt.transcribe, audio)
        t_stt = time.monotonic()
        if self.save_audio:
            self._save(audio, text)
        if not text:
            self._set(IDLE, note="heard nothing")
            return
        self._set(THINKING, heard=text)
        print(f"\nyou : {text}", flush=True)

        if cmd := commands.parse(text):  # personality settings: no LLM round-trip
            confirmation = commands.apply(self.cfg, *cmd)
            await self._say(confirmation)
            print(f"tars: {confirmation}", flush=True)
            self._set(IDLE)
            return

        if (route := router.match(text, self.sites)) and await self._fast_path(
            text, route, t_stt - t_release
        ):
            return

        facts = [f for _, f in self.memory.facts(text, limit=4)]
        messages = [
            {
                "role": "system",
                "content": system_prompt(
                    self.cfg, can_act=True, facts=facts, sites=self.site_names
                ),
            },
            *self.history[-2 * self.cfg["llm"].get("history_turns", 8) :],
            {"role": "user", "content": stamp(text)},
        ]

        chunks: asyncio.Queue[str | None] = asyncio.Queue()
        marks: dict[str, float] = {}
        chunker = SpeechChunker()

        async def speak():
            while (chunk := await chunks.get()) is not None:
                samples = await asyncio.to_thread(self.tts.synth, chunk)
                if "audio" not in marks:
                    marks["audio"] = time.monotonic()
                self._set(SPEAKING)
                self.player.enqueue(samples)

        def on_text(delta: str):
            marks.setdefault("token", time.monotonic())
            for c in chunker.feed(delta):
                chunks.put_nowait(c)

        def on_tool(name: str, args: dict):
            marks.setdefault("token", time.monotonic())
            print(f"      · {name}({args})", flush=True)
            if "narrated" not in marks and (line := self._narration(name, args)):
                marks["narrated"] = time.monotonic()
                chunks.put_nowait(line)

        speaker = asyncio.create_task(speak())
        try:
            result = await run_turn(
                messages, self.registry, self.ctx,
                self.cfg["llm"]["endpoint"], self.cfg["llm"]["brain"],
                on_text=on_text, on_tool=on_tool,
                max_tokens=400, temperature=0.3, top_p=0.8,
            )  # fmt: skip
            for c in chunker.flush():
                chunks.put_nowait(c)
            chunks.put_nowait(None)
            await speaker
            await asyncio.to_thread(self.player.wait_idle)
        except asyncio.CancelledError:
            speaker.cancel()
            print("tars: (interrupted)", flush=True)
            raise

        # History keeps the spoken answer plus a compact, unspoken note of what was done,
        # so follow-ups ("move it to Documents") know what "it" is.
        note = "; ".join(f"{s['tool']}({s['args']}) -> {s['result'][:80]}" for s in result.steps)
        self.history += [
            {"role": "user", "content": text},
            {
                "role": "assistant",
                "content": result.answer + (f"\n[done: {note[:500]}]" if note else ""),
            },
        ]
        self.memory.add_turn(text, result.answer)
        print(f"tars: {result.answer}", flush=True)
        ms = lambda k: round((marks[k] - t_release) * 1000) if k in marks else None  # noqa: E731
        print(
            f"      [stt {round((t_stt - t_release) * 1000)} ms · first token {ms('token')} ms"
            f" · first audio {ms('audio')} ms · {len(result.steps)} tool calls]",
            flush=True,
        )
        self._set(IDLE)
