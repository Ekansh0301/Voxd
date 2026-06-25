#!/usr/bin/env python3
"""
launch_pygpt.py — Launch PyGPT with Flash plugins pre-registered
================================================================================
Run this INSTEAD of `pygpt` if you want the full PyGPT UI
with Flash Avatar and Piper TTS baked in.

Usage:
    source venv/bin/activate
    python3 launch_pygpt.py
================================================================================
"""

import sys
import os
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
PLUGIN_DIR  = PROJECT_DIR / 'plugins'

# Ensure Flash plugins are on path
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(PROJECT_DIR))

# ── Load our config ───────────────────────────────────────────────────────────
config_path = PROJECT_DIR / 'config' / 'config.json'
with open(config_path) as f:
    flash_config = json.load(f)

model      = flash_config.get('model', 'qwen2.5-coder:3b')
voice      = flash_config.get('voice', 'en_US-ryan-high')
voices_dir = str(PROJECT_DIR / flash_config.get('voices_dir', 'voices'))

# ── Patch PyGPT to register our plugins before launch ─────────────────────────
def patch_and_launch():
    try:
        from pygpt_net.app import run
        from pygpt_net.container import Container

        # Pre-configure Ollama endpoint
        os.environ['OPENAI_API_BASE'] = 'http://localhost:11434/v1'
        os.environ['OPENAI_API_KEY']  = 'ollama'  # Ollama ignores API keys

        print(f"\n[Flash] Launching PyGPT with:")
        print(f"  Model:  {model}")
        print(f"  Voice:  {voice}")
        print(f"  Voices: {voices_dir}")
        print(f"  Plugins: Piper TTS + Flash Avatar\n")

        # Run PyGPT — plugins will be picked up from ~/.config/pygpt-net/plugins/
        run()

    except ImportError as e:
        print(f"ERROR: PyGPT not installed: {e}")
        print("Install with: pip install pygpt-net")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR launching PyGPT: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def install_plugins_to_pygpt():
    """Copy Flash plugins to PyGPT's plugin directory."""
    pygpt_plugin_dir = Path.home() / '.config' / 'pygpt-net' / 'plugins'
    pygpt_plugin_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    for plugin in ['plugin_piper_tts', 'plugin_flash_avatar']:
        src = PLUGIN_DIR / plugin
        dst = pygpt_plugin_dir / plugin
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"[Flash] Installed plugin: {plugin} → {dst}")
        else:
            print(f"[Flash] Plugin source not found: {src}")

    # Update plugin config to point to our voices
    plugin_config = {
        'plugin_piper_tts': {
            'voices_dir': voices_dir,
            'voice_model': voice,
            'speed': flash_config.get('tts_speed', 0.95),
            'enabled': True,
        },
        'plugin_flash_avatar': {
            'enabled': flash_config.get('avatar_enabled', True),
        }
    }

    config_out = pygpt_plugin_dir / 'flash_plugin_config.json'
    with open(config_out, 'w') as f:
        json.dump(plugin_config, f, indent=2)
    print(f"[Flash] Plugin config written: {config_out}")


if __name__ == '__main__':
    print("Installing Flash plugins into PyGPT...")
    install_plugins_to_pygpt()
    print("Launching PyGPT...\n")
    patch_and_launch()
