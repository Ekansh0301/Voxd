"""
core/hotkey_listener.py — Push-to-Talk Hotkey
================================================================================
Listens globally for a configurable key.
While held: recording
On release: stops recording, triggers transcription

Supported hotkey strings:
  'ctrl_r'       → Right Control
  'ctrl_l'       → Left Control
  'alt_r'        → Right Alt
  'scroll_lock'  → Scroll Lock
  'pause'        → Pause/Break
  'f12'          → F12
  'f10'          → F10
  'caps_lock'    → Caps Lock (use carefully)

Does NOT block the rest of the OS — uses pynput in a daemon thread.
================================================================================
"""

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("flash.hotkey")


# Map friendly names to pynput Key objects
KEY_MAP = {
    "ctrl_r": None,  # resolved dynamically
    "ctrl_l": None,
    "alt_r": None,
    "alt_l": None,
    "shift_r": None,
    "scroll_lock": None,
    "pause": None,
    "f10": None,
    "f11": None,
    "f12": None,
    "caps_lock": None,
    "insert": None,
    "home": None,
    "end": None,
    "page_up": None,
    "page_down": None,
}


class HotkeyListener:
    """
    Listens for a push-to-talk key globally.
    Calls on_press when key goes down, on_release when key comes up.
    """

    def __init__(
        self,
        hotkey: str = "ctrl_r",
        on_press: Optional[Callable] = None,
        on_release: Optional[Callable] = None,
    ):
        self.hotkey_name = hotkey
        self.on_press_cb = on_press
        self.on_release_cb = on_release
        self._listener = None
        self._active = False
        self._key_held = False
        self._thread = None

        self._target_key = self._resolve_key(hotkey)

    def _resolve_key(self, name: str):
        """Convert string name to pynput Key object."""
        try:
            from pynput.keyboard import Key

            key_map = {
                "ctrl_r": Key.ctrl_r,
                "ctrl_l": Key.ctrl_l,
                "alt_r": Key.alt_r,
                "alt_l": Key.alt_l,
                "shift_r": Key.shift_r,
                "scroll_lock": Key.scroll_lock,
                "pause": Key.pause,
                "f10": Key.f10,
                "f11": Key.f11,
                "f12": Key.f12,
                "caps_lock": Key.caps_lock,
                "insert": Key.insert,
                "home": Key.home,
                "end": Key.end,
                "page_up": Key.page_up,
                "page_down": Key.page_down,
            }
            key = key_map.get(name.lower())
            if key is None:
                log.warning(f"Unknown hotkey '{name}'. Defaulting to ctrl_r.")
                key = Key.ctrl_r
            log.info(f"Push-to-talk key: {key}")
            return key
        except ImportError:
            log.error("pynput not installed. Run: pip install pynput")
            return None

    def start(self):
        """Start listening in a background thread."""
        if self._target_key is None:
            log.error("Cannot start hotkey listener — no key resolved.")
            return

        self._active = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        log.info(f"Hotkey listener started: hold [{self.hotkey_name}] to talk")

    def stop(self):
        """Stop the listener."""
        self._active = False
        if self._listener:
            self._listener.stop()

    def _listen(self):
        from pynput.keyboard import Listener

        def on_press(key):
            if not self._active:
                return False  # Stop listener
            try:
                if key == self._target_key and not self._key_held:
                    self._key_held = True
                    log.debug(f"PTT key pressed: {key}")
                    if self.on_press_cb:
                        self.on_press_cb()
            except Exception as e:
                log.error(f"on_press error: {e}")

        def on_release(key):
            if not self._active:
                return False
            try:
                if key == self._target_key and self._key_held:
                    self._key_held = False
                    log.debug(f"PTT key released: {key}")
                    if self.on_release_cb:
                        self.on_release_cb()
            except Exception as e:
                log.error(f"on_release error: {e}")

        try:
            with Listener(
                on_press=on_press,
                on_release=on_release,
                suppress=False,  # Don't block the key from other apps
            ) as listener:
                self._listener = listener
                listener.join()
        except Exception as e:
            log.error(f"Hotkey listener error: {e}")

    def change_hotkey(self, new_hotkey: str):
        """Change the PTT key at runtime."""
        self.stop()
        self.hotkey_name = new_hotkey
        self._target_key = self._resolve_key(new_hotkey)
        self._key_held = False
        self.start()
