#!/usr/bin/env python3
"""
test_all.py — Full component test suite
================================================================================
Run this after installation to verify every subsystem works.
Usage:
    source venv/bin/activate
    python3 test_all.py
    python3 test_all.py --component tts
    python3 test_all.py --component stt
    python3 test_all.py --component brain
    python3 test_all.py --component desktop
    python3 test_all.py --component memory
================================================================================
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

# Colours
G = '\033[92m'
R = '\033[91m'
Y = '\033[93m'
B = '\033[94m'
C = '\033[96m'
W = '\033[1m'
N = '\033[0m'

def ok(msg):    print(f"  {G}✓{N}  {msg}")
def fail(msg):  print(f"  {R}✗{N}  {msg}")
def warn(msg):  print(f"  {Y}!{N}  {msg}")
def info(msg):  print(f"  {B}i{N}  {msg}")
def head(msg):  print(f"\n{W}{C}{msg}{N}")


# ══════════════════════════════════════════════════════════════════════════════
def test_system():
    head("[ System ]")

    import platform
    info(f"OS: {platform.platform()}")
    info(f"Python: {sys.version.split()[0]}")

    # GPU
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total',
             '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            ok(f"GPU: {result.stdout.strip()}")
        else:
            warn("nvidia-smi returned error — check NVIDIA drivers")
    except FileNotFoundError:
        warn("nvidia-smi not found — GPU unavailable")

    # xdotool
    result = subprocess.run(['which', 'xdotool'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        ok("xdotool: available")
    else:
        fail("xdotool not found — run: sudo apt install xdotool")

    # espeak-ng (fallback TTS)
    result = subprocess.run(['which', 'espeak-ng'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        ok("espeak-ng: available (TTS fallback)")
    else:
        warn("espeak-ng not found — install: sudo apt install espeak-ng")


# ══════════════════════════════════════════════════════════════════════════════
def test_ollama():
    head("[ Ollama / LLM Brain ]")

    import requests
    try:
        r = requests.get('http://localhost:11434', timeout=3)
        ok("Ollama: running on port 11434")
    except Exception as e:
        fail(f"Ollama not reachable: {e}")
        fail("Start with: ollama serve")
        return

    # List models
    try:
        r = requests.get('http://localhost:11434/api/tags', timeout=5)
        models = r.json().get('models', [])
        if models:
            for m in models:
                ok(f"Model available: {m['name']}")
        else:
            warn("No models pulled. Run: ollama pull qwen2.5-coder:3b")
    except Exception as e:
        warn(f"Could not list models: {e}")

    # Quick inference test
    info("Testing inference (this takes 5-15s first time)...")
    try:
        start = time.time()
        r = requests.post(
            'http://localhost:11434/api/chat',
            json={
                "model": "qwen2.5-coder:3b",
                "messages": [{"role": "user", "content": "Say: OK"}],
                "stream": False,
                "options": {"num_predict": 10}
            },
            timeout=30
        )
        elapsed = time.time() - start
        if r.status_code == 200:
            reply = r.json().get('message', {}).get('content', '')
            ok(f"Inference: '{reply.strip()}' in {elapsed:.1f}s")
        else:
            fail(f"Inference failed: HTTP {r.status_code}")
    except Exception as e:
        fail(f"Inference test failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
def test_stt():
    head("[ STT — Whisper ]")

    try:
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        ok(f"PyTorch: {torch.__version__}, device={device}")
        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory // 1024**2
            ok(f"CUDA VRAM: {vram}MB")
    except ImportError:
        fail("PyTorch not installed")
        return

    try:
        from faster_whisper import WhisperModel
        info("Loading Whisper Tiny (may take a moment)...")
        start = time.time()
        model = WhisperModel('tiny', device=device,
                             compute_type='float16' if device == 'cuda' else 'int8')
        ok(f"Whisper Tiny loaded in {time.time()-start:.1f}s on {device}")

        # Test with silent audio
        import numpy as np
        silent = np.zeros(16000, dtype=np.float32)
        segs, info_obj = model.transcribe(silent, beam_size=1)
        list(segs)  # consume generator
        ok("Whisper transcription pipeline: functional")

    except ImportError:
        fail("faster-whisper not installed: pip install faster-whisper")
    except Exception as e:
        fail(f"Whisper test failed: {e}")

    # Test microphone
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if d['max_input_channels'] > 0]
        if input_devs:
            ok(f"Microphone devices: {len(input_devs)} found")
            for d in input_devs[:3]:
                info(f"  [{d['index']}] {d['name']}")
        else:
            warn("No microphone devices found")
    except Exception as e:
        warn(f"Could not query audio devices: {e}")


# ══════════════════════════════════════════════════════════════════════════════
def test_tts():
    head("[ TTS — Piper ]")

    voices_dir = PROJECT_DIR / 'voices'
    onnx_files = list(voices_dir.glob('*.onnx'))

    if not onnx_files:
        fail(f"No voice models in {voices_dir}")
        fail("Run scripts/install.sh to download voices")
        return

    for v in onnx_files:
        json_file = voices_dir / (v.name + '.json')
        if json_file.exists():
            ok(f"Voice: {v.stem}")
        else:
            warn(f"Voice {v.stem} missing .json config")

    # Test synthesis
    voice_file = onnx_files[0]
    info(f"Testing synthesis with: {voice_file.stem}")

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Try Python module
        proc = subprocess.run(
            ['python3', '-m', 'piper',
             '--model', str(voice_file),
             '--output_file', tmp_path],
            input=b"Flash Copilot is ready.",
            capture_output=True,
            timeout=15
        )
        if proc.returncode == 0 and os.path.getsize(tmp_path) > 1000:
            ok(f"Piper synthesis: OK ({os.path.getsize(tmp_path)} bytes)")

            # Try playback
            play_result = subprocess.run(
                ['aplay', tmp_path],
                capture_output=True,
                timeout=10
            )
            if play_result.returncode == 0:
                ok("Audio playback: OK (you should have heard a voice)")
            else:
                warn("aplay failed — try: sudo apt install alsa-utils")
        else:
            fail(f"Piper synthesis failed: {proc.stderr.decode()[:200]}")

            # Try CLI
            info("Trying piper CLI directly...")
            proc2 = subprocess.run(
                ['piper', '--model', str(voice_file),
                 '--output_file', tmp_path],
                input=b"Test",
                capture_output=True, timeout=15
            )
            if proc2.returncode == 0:
                ok("Piper CLI: OK")
            else:
                fail("Piper CLI also failed")
                fail("Reinstall: pip install piper-tts")

    except subprocess.TimeoutExpired:
        fail("Piper synthesis timed out (>15s)")
    except FileNotFoundError:
        fail("Python3 not found in PATH")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
def test_desktop():
    head("[ Desktop Control ]")

    from core.desktop_control import DesktopControl
    dc = DesktopControl()

    # System info
    info_str = dc.get_system_info()
    if 'CPU' in info_str:
        ok("System info: working")
        for line in info_str.split('\n')[:4]:
            info(line.strip())
    else:
        warn(f"System info: {info_str}")

    # Command execution
    stdout, stderr = dc.run_command('echo "Flash test OK"')
    if 'Flash test OK' in stdout:
        ok("Command execution: working")
    else:
        fail(f"Command execution failed: {stderr}")

    # Web search
    info("Testing web search (needs internet)...")
    try:
        result = dc.web_search("Python programming", max_results=2)
        if result and len(result) > 50:
            ok("Web search: working")
        else:
            warn("Web search returned empty results")
    except Exception as e:
        warn(f"Web search: {e}")

    # File read
    test_file = PROJECT_DIR / 'config' / 'config.json'
    content = dc.read_file(str(test_file))
    if 'model' in content:
        ok("File read: working")
    else:
        fail(f"File read failed: {content}")

    # xdotool
    result = subprocess.run(['which', 'xdotool'], capture_output=True)
    if result.returncode == 0:
        ok("xdotool: available for keyboard/window control")
    else:
        warn("xdotool missing: sudo apt install xdotool")


# ══════════════════════════════════════════════════════════════════════════════
def test_memory():
    head("[ Memory — ChromaDB ]")

    try:
        import chromadb
        ok(f"ChromaDB: {chromadb.__version__}")
    except ImportError:
        fail("ChromaDB not installed: pip install chromadb")
        return

    try:
        from core.memory_engine import MemoryEngine
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mem = MemoryEngine(Path(tmp))
            if not mem._ready:
                fail("Memory engine failed to initialize")
                return

            ok("Memory engine: initialized")

            # Save and recall
            mem.save(
                "open chrome and search for AI papers",
                "Opening Chrome and searching for AI papers now."
            )
            mem.save(
                "check disk space",
                "You have 45GB free on /dev/sda1."
            )
            ok("Memory save: working")

            recall = mem.recall("chrome browser")
            if recall:
                ok(f"Memory recall: found {len(recall)} chars of context")
            else:
                warn("Memory recall: nothing found (may need more data)")

            info(f"Total memories: {mem.count}")

    except Exception as e:
        fail(f"Memory test failed: {e}")
        import traceback
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════════
def test_hotkey():
    head("[ Hotkey Listener ]")

    try:
        from pynput.keyboard import Key
        ok("pynput: installed")

        from core.hotkey_listener import HotkeyListener
        listener = HotkeyListener(hotkey='ctrl_r')
        if listener._target_key is not None:
            ok(f"Hotkey resolved: {listener._target_key}")
        else:
            warn("Hotkey could not be resolved")

        info("NOTE: Actual hotkey test requires a display and a keypress.")
        info("Hold Right Ctrl when running the full app to test PTT.")

    except ImportError:
        fail("pynput not installed: pip install pynput")
    except Exception as e:
        fail(f"Hotkey test failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
def test_safety():
    head("[ Safety Layer ]")

    from core.safety import SafetyLayer
    s = SafetyLayer()

    safe_cmds = [
        'ls -la', 'cat /etc/hostname', 'ps aux',
        'df -h', 'free -m', 'journalctl -n 10',
    ]
    risky_cmds = [
        'sudo apt install vim', 'systemctl stop nginx',
        'pip install numpy', 'kill 1234',
    ]
    blocked_cmds = [
        'rm -rf /', 'dd if=/dev/zero of=/dev/sda',
    ]

    ok("Safe commands (auto-approve):")
    for cmd in safe_cmds:
        needs = s.needs_confirmation(cmd)
        label = f"{'NEEDS CONFIRM' if needs else 'AUTO-SAFE':15}"
        color = Y if needs else G
        print(f"    {color}{label}{N}  {cmd}")

    ok("Risky commands (need confirmation):")
    for cmd in risky_cmds:
        needs  = s.needs_confirmation(cmd)
        blocked = s.is_blocked(cmd)
        risk = s.get_risk_label(cmd)
        color = R if blocked else (Y if needs else G)
        print(f"    {color}{risk:10}{N}  {cmd}")

    ok("Catastrophically dangerous (always blocked):")
    for cmd in blocked_cmds:
        blocked = s.is_blocked(cmd)
        status = f"{R}BLOCKED{N}" if blocked else f"{G}not blocked{N}"
        print(f"    {status}  {cmd}")


# ══════════════════════════════════════════════════════════════════════════════
TESTS = {
    'system':  test_system,
    'brain':   test_ollama,
    'stt':     test_stt,
    'tts':     test_tts,
    'desktop': test_desktop,
    'memory':  test_memory,
    'hotkey':  test_hotkey,
    'safety':  test_safety,
}


def main():
    parser = argparse.ArgumentParser(description='Flash Copilot test suite')
    parser.add_argument(
        '--component', '-c',
        choices=list(TESTS.keys()) + ['all'],
        default='all',
        help='Which component to test'
    )
    args = parser.parse_args()

    print(f"\n{W}{C}Flash Copilot — Diagnostic Suite{N}")
    print("=" * 50)

    if args.component == 'all':
        for name, fn in TESTS.items():
            try:
                fn()
            except Exception as e:
                fail(f"Test {name} crashed: {e}")
    else:
        TESTS[args.component]()

    print(f"\n{'=' * 50}")
    print(f"{W}Done.{N} Fix any {R}✗{N} errors before launching.\n")


if __name__ == '__main__':
    main()
