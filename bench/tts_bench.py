"""
Text-to-speech benchmark on CPU: Piper vs Kokoro-82M (int8 and fp32 builds).

Measures time to synthesise a short first sentence (what you wait for before
TARS starts talking) and real-time factor on a longer reply, and writes WAVs
to bench/results/tts/ so you can listen and pick a voice.

    .venv/bin/python -m bench.tts_bench
"""

import json
import statistics
import time
from pathlib import Path

import soundfile as sf

from tars import MODELS_DIR

HERE = Path(__file__).parent
OUT = HERE / "results" / "tts"
PIPER_VOICES = MODELS_DIR / "tts" / "piper"
KOKORO = MODELS_DIR / "tts"

SHORT = "Draft ready for Rahul. Want me to read it?"
LONG = (
    "I found three unread emails. The professor moved Thursday's lab to Friday at ten. "
    "Rahul is asking when the report will be ready, and there is a reminder about the "
    "hostel fee deadline. Do you want me to draft a reply to Rahul first?"
)

PIPER_VARIANTS = ["en_US-ryan-high", "en_US-lessac-high", "en_US-lessac-medium"]
KOKORO_VARIANTS = ["am_michael", "am_fenrir", "bm_george", "bm_lewis", "af_heart", "bf_emma"]


def bench_piper() -> list[dict]:
    """Piper with the voice loaded once, as the TARS voice service runs it."""
    import wave

    from piper import PiperVoice

    def synth(voice, text: str, out: Path) -> float:
        with wave.open(str(out), "wb") as w:
            voice.synthesize_wav(text, w)
        return float(sf.info(out).duration)

    rows = []
    for v in PIPER_VARIANTS:
        path = PIPER_VOICES / f"{v}.onnx"
        if not path.exists():
            continue
        t = time.monotonic()
        voice = PiperVoice.load(str(path))
        load_s = time.monotonic() - t
        synth(voice, "warm up", OUT / "warmup.wav")
        short = []
        for _ in range(3):
            t = time.monotonic()
            synth(voice, SHORT, OUT / f"piper-{v}-short.wav")
            short.append(time.monotonic() - t)
        t = time.monotonic()
        dur = synth(voice, LONG, OUT / f"piper-{v}-long.wav")
        long_s = time.monotonic() - t
        rows.append(
            {"engine": "piper", "voice": v, "short_ms": round(statistics.median(short) * 1000),
             "long_rtf": round(long_s / dur, 3), "long_audio_s": round(dur, 1),
             "load_s": round(load_s, 1)}
        )  # fmt: skip
        print(rows[-1], flush=True)
    (OUT / "warmup.wav").unlink(missing_ok=True)
    return rows


def bench_kokoro() -> list[dict]:
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        return [{"engine": "kokoro", "error": "kokoro-onnx not installed"}]
    voices = KOKORO / "voices-v1.0.bin"
    rows: list[dict] = []
    for build, fname in (("int8", "kokoro-v1.0.int8.onnx"), ("fp32", "kokoro-v1.0.onnx")):
        model = KOKORO / fname
        if not model.exists() or (model.with_name(fname + ".part")).exists():
            rows.append({"engine": f"kokoro-{build}", "error": f"missing {model.name}"})
            continue
        t = time.monotonic()
        k = Kokoro(str(model), str(voices))
        load_s = time.monotonic() - t
        k.create("warm up", voice=KOKORO_VARIANTS[0], speed=1.0, lang="en-us")
        for v in KOKORO_VARIANTS:
            lang = "en-gb" if v.startswith("b") else "en-us"
            short = []
            for _ in range(3):
                t = time.monotonic()
                samples, sr = k.create(SHORT, voice=v, speed=1.0, lang=lang)
                short.append(time.monotonic() - t)
            sf.write(OUT / f"kokoro-{build}-{v}-short.wav", samples, sr)
            t = time.monotonic()
            samples, sr = k.create(LONG, voice=v, speed=1.0, lang=lang)
            long_s = time.monotonic() - t
            sf.write(OUT / f"kokoro-{build}-{v}-long.wav", samples, sr)
            dur = len(samples) / sr
            rows.append(
                {"engine": f"kokoro-{build}", "voice": v,
                 "short_ms": round(statistics.median(short) * 1000),
                 "long_rtf": round(long_s / dur, 3), "long_audio_s": round(dur, 1),
                 "load_s": round(load_s, 1)}
            )  # fmt: skip
            print(rows[-1], flush=True)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = bench_piper() + bench_kokoro()
    (HERE / "results" / "tts.json").write_text(json.dumps(rows, indent=2))
    print(f"\nListen: {OUT}")


if __name__ == "__main__":
    main()
