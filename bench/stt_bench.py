"""
Speech-to-text benchmark on YOUR recordings (bench/record_commands.py first).

Measures word error rate, recall of names/places/tech words (what matters for
commands), and latency, for each faster-whisper candidate on CPU (and one GPU
reference run).

    .venv/bin/python -m bench.stt_bench
    .venv/bin/python -m bench.stt_bench -v small.en-cpu,medium.en-cpu+hot
"""

import argparse
import inspect
import json
import re
import statistics
import time
from pathlib import Path

import jiwer
import soundfile as sf
from faster_whisper import WhisperModel

from tars import MODELS_DIR

HERE = Path(__file__).parent
VOICE = HERE / "data" / "voice"
RESULTS = HERE / "results"
STT = MODELS_DIR / "stt"

# Names, places and words whisper tends to miss; also used as `hotwords`.
ENTITIES = [
    "TARS", "Outlook", "WhatsApp", "Rahul", "Priya", "Ananya", "Srinivas", "IIIT", "Moodle",
    "Gachibowli", "Hitech City", "Hyderabad", "Delhi", "Swiggy", "LeetCode", "Arijit Singh",
    "Godavari", "CUDA", "VRAM", "Ollama", "pytest", "GitHub", "Jupyter", "DSA", "sem5",
    "Spotify", "YouTube", "lofi", "Firefox", "VS Code", "llama dot cpp", "nvidia smi",
]  # fmt: skip
HOTWORDS = ", ".join(ENTITIES)

VARIANTS = {
    # name: (model path or id, device, compute_type, use_hotwords)
    "small.en-cpu": (STT / "small.en", "cpu", "int8", False),
    "small.en-cpu+hot": (STT / "small.en", "cpu", "int8", True),
    "distil-small.en-cpu": (STT / "distil-small.en", "cpu", "int8", False),
    "medium.en-cpu": (STT / "medium.en", "cpu", "int8", False),
    "medium.en-cpu+hot": (STT / "medium.en", "cpu", "int8", True),
    "small-multi-cpu (v1 model)": ("small", "cpu", "int8", False),
    "small.en-gpu (reference)": (STT / "small.en", "cuda", "int8_float16", False),
}

_NUM = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
_NUM.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "hundred": "100"})


def normalize(s: str) -> str:
    s = s.lower().replace("a.m.", "am").replace("p.m.", "pm").replace("%", " percent")
    s = re.sub(r"(?<=\w)\.(?=\w)", " dot ", s)  # llama.cpp -> llama dot cpp
    s = s.replace("-", " ").replace("'", "")
    s = re.sub(r"[^\w\s]", " ", s)
    words = [_NUM.get(w, w) for w in s.split()]
    return " ".join(words)


def load_set() -> list[dict]:
    manifest = VOICE / "manifest.jsonl"
    if not manifest.exists():
        raise SystemExit("No recordings yet. Run: .venv/bin/python -m bench.record_commands")
    return [json.loads(line) for line in manifest.read_text().splitlines() if line]


def run_variant(name: str, items: list[dict]) -> dict:
    src, device, compute, hot = VARIANTS[name]
    if isinstance(src, Path) and not src.exists():
        return {"variant": name, "error": f"missing {src}"}
    t0 = time.monotonic()
    model = WhisperModel(str(src), device=device, compute_type=compute, cpu_threads=6)
    load_s = time.monotonic() - t0
    kw: dict = {
        "language": "en", "beam_size": 1, "vad_filter": False,
        "condition_on_previous_text": False, "without_timestamps": True,
    }  # fmt: skip
    if hot:
        if "hotwords" not in inspect.signature(model.transcribe).parameters:
            return {"variant": name, "error": "this faster-whisper has no hotwords option"}
        kw["hotwords"] = HOTWORDS

    refs, hyps, lat, audio_s, ent_hit, ent_total, worst = [], [], [], 0.0, 0, 0, []
    model.transcribe(sf.read(VOICE / items[0]["file"], dtype="float32")[0], **kw)  # warm-up
    for it in items:
        audio, _ = sf.read(VOICE / it["file"], dtype="float32")
        t = time.monotonic()
        segs, _ = model.transcribe(audio, **kw)
        hyp = " ".join(s.text for s in segs).strip()
        lat.append((time.monotonic() - t) * 1000)
        audio_s += len(audio) / 16000
        r, h = normalize(it["text"]), normalize(hyp)
        refs.append(r)
        hyps.append(h)
        for e in ENTITIES:
            if normalize(e) in r:
                ent_total += 1
                ent_hit += normalize(e) in h
        if r != h:
            worst.append({"said": it["text"], "heard": hyp, "wer": round(jiwer.wer(r, h), 2)})
    worst.sort(key=lambda w: -w["wer"])
    return {
        "variant": name,
        "n": len(items),
        "wer": round(jiwer.wer(refs, hyps), 4),
        "sentence_exact": round(sum(r == h for r, h in zip(refs, hyps)) / len(refs), 3),
        "entity_recall": round(ent_hit / ent_total, 3) if ent_total else None,
        "latency_ms_median": round(statistics.median(lat)),
        "latency_ms_p90": round(sorted(lat)[int(len(lat) * 0.9) - 1]),
        "rtf": round(sum(lat) / 1000 / audio_s, 3),
        "load_s": round(load_s, 1),
        "worst": worst[:12],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--variants", default="all")
    args = ap.parse_args()
    items = load_set()
    names = list(VARIANTS) if args.variants == "all" else args.variants.split(",")
    RESULTS.mkdir(exist_ok=True)
    out = []
    for n in names:
        print(f"== {n}", flush=True)
        res = run_variant(n, items)
        out.append(res)
        print({k: v for k, v in res.items() if k != "worst"}, flush=True)
    (RESULTS / "stt.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
