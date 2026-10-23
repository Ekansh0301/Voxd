"""
Record your own voice commands for the STT benchmark (about 10 minutes).

    .venv/bin/python -m bench.record_commands

For each sentence: press Enter to start, say it the way you normally would,
press Enter to stop. Then Enter = keep, r = redo, s = skip, q = quit.
Re-running resumes where you left off. Recordings stay on this machine in
bench/data/voice/ (gitignored).
"""

import json
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

HERE = Path(__file__).parent
VOICE = HERE / "data" / "voice"
SR = 16000


def record_until_enter() -> np.ndarray:
    chunks: list[np.ndarray] = []
    stop = threading.Event()

    def cb(indata, frames, t, status):
        chunks.append(indata.copy())

    def wait_for_enter():
        input()
        stop.set()

    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=cb):
        threading.Thread(target=wait_for_enter, daemon=True).start()
        stop.wait()
    return np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype="float32")


def main():
    VOICE.mkdir(parents=True, exist_ok=True)
    manifest = VOICE / "manifest.jsonl"
    done = set()
    if manifest.exists():
        done = {json.loads(line)["file"] for line in manifest.read_text().splitlines() if line}
    sentences = [s.strip() for s in (HERE / "data" / "commands.txt").read_text().splitlines()]
    sentences = [s for s in sentences if s]
    print(f"Mic: {sd.query_devices(kind='input')['name']}")
    print(f"{len(done)}/{len(sentences)} already recorded.\n")

    for i, text in enumerate(sentences, 1):
        fname = f"{i:03d}.wav"
        if fname in done:
            continue
        while True:
            print(f'[{i}/{len(sentences)}]  "{text}"')
            cmd = input("  Enter = start recording (s = skip, q = quit): ").strip().lower()
            if cmd == "q":
                return
            if cmd == "s":
                break
            print("  ● recording… press Enter to stop")
            audio = record_until_enter()
            dur, peak = len(audio) / SR, float(np.abs(audio).max()) if len(audio) else 0.0
            note = "  (very quiet — move closer?)" if peak < 0.05 else ""
            print(f"  {dur:.1f}s, peak {peak:.2f}{note}")
            ans = input("  Enter = keep, r = redo: ").strip().lower()
            if ans == "r":
                continue
            sf.write(VOICE / fname, audio, SR)
            with manifest.open("a") as f:
                f.write(json.dumps({"file": fname, "text": text}) + "\n")
            break
    print("\nAll done. Run: .venv/bin/python -m bench.stt_bench")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
