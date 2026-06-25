#!/usr/bin/env python3
"""
Flash Copilot — Main Application
================================================================================
A Jarvis-style local AI avatar for Ubuntu.
- PyQt6 animated floating orb (always-on-top)
- Push-to-talk via configurable hotkey (never always-listening)
- Whisper Tiny STT (faster-whisper, CUDA)
- Ollama LLM (Qwen2.5-Coder 3B/7B) with dynamic tool calling
- Piper TTS (local, no VRAM cost, natural voice)
- Full desktop control (xdotool, subprocess, pyautogui)
- Persistent memory (ChromaDB local)
- System tray integration
================================================================================
"""

import sys
import os
import json
import re
import subprocess
import threading
import time
import queue
import logging
import argparse
import signal
from pathlib import Path
from typing import Optional

# ── Qt imports ────────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu,
    QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QLineEdit, QScrollArea, QFrame,
    QSizePolicy, QSplitter
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QPoint, QRect, pyqtProperty, QObject,
    QSize
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QIcon,
    QRadialGradient, QPainterPath, QPixmap, QTextCursor,
    QKeySequence, QShortcut
)

# ── Project imports ───────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from core.voice_engine import VoiceEngine
from core.brain import Brain, _format_for_speech
from core.desktop_control import DesktopControl
from core.memory_engine import MemoryEngine
from core.hotkey_listener import HotkeyListener
from core.safety import SafetyLayer
from core.monitor import ProactiveMonitor
from core.plugin_loader import PluginLoader

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / 'flash_copilot.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('flash')


# ══════════════════════════════════════════════════════════════════════════════
#  AVATAR STATES
# ══════════════════════════════════════════════════════════════════════════════
class AvatarState:
    IDLE      = 'idle'       # Breathing pulse, soft glow
    LISTENING = 'listening'  # Waveform animation, bright blue
    THINKING  = 'thinking'   # Spinning arcs, amber
    SPEAKING  = 'speaking'   # Bouncing orb, green
    ERROR     = 'error'      # Red flash


# ══════════════════════════════════════════════════════════════════════════════
#  ANIMATED AVATAR WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class AvatarWidget(QWidget):
    """
    Floating animated orb that lives in the corner of the screen.
    Always-on-top, frameless, click-through when idle.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = AvatarState.IDLE
        self._anim_tick = 0.0
        self._wave_bars = [0.0] * 12
        self._spin_angle = 0.0
        self._pulse_scale = 1.0
        self._bounce_y = 0.0
        self._opacity = 0.0
        self._text = ""
        self._subtext = ""

        # Window setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(240, 280)

        # Position: bottom-right corner
        self._reposition()

        # Animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30fps

        # Fade in
        self._fade_in()

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 260, screen.height() - 300)

    def _fade_in(self):
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._do_fade)
        self._fade_timer.start(20)

    def _do_fade(self):
        self._opacity = min(1.0, self._opacity + 0.05)
        self.update()
        if self._opacity >= 1.0:
            self._fade_timer.stop()

    def set_state(self, state: str, text: str = "", subtext: str = ""):
        self.state = state
        self._text = text
        self._subtext = subtext
        self.update()

    def set_text(self, text: str, subtext: str = ""):
        self._text = text
        self._subtext = subtext
        self.update()

    def _tick(self):
        self._anim_tick += 0.05
        dt = 0.05

        if self.state == AvatarState.IDLE:
            self._pulse_scale = 1.0 + 0.06 * abs(
                __import__('math').sin(self._anim_tick * 0.8)
            )

        elif self.state == AvatarState.LISTENING:
            import random, math
            for i in range(len(self._wave_bars)):
                target = 0.3 + 0.7 * abs(math.sin(
                    self._anim_tick * 3 + i * 0.7
                ))
                self._wave_bars[i] += (target - self._wave_bars[i]) * 0.3
            self._pulse_scale = 1.0

        elif self.state == AvatarState.THINKING:
            self._spin_angle = (self._spin_angle + 4) % 360
            self._pulse_scale = 1.0

        elif self.state == AvatarState.SPEAKING:
            import math
            self._bounce_y = 4 * math.sin(self._anim_tick * 6)
            self._pulse_scale = 1.0 + 0.04 * abs(
                math.sin(self._anim_tick * 4)
            )

        self.update()

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)

        cx, cy = 120, 120
        r = 72

        # ── Background circle ──────────────────────────────────────────────
        bg_color = {
            AvatarState.IDLE:      QColor(15, 15, 25, 200),
            AvatarState.LISTENING: QColor(5, 20, 40, 210),
            AvatarState.THINKING:  QColor(25, 15, 5, 210),
            AvatarState.SPEAKING:  QColor(5, 25, 10, 210),
            AvatarState.ERROR:     QColor(40, 5, 5, 210),
        }.get(self.state, QColor(15, 15, 25, 200))

        p.setBrush(QBrush(bg_color))
        p.setPen(Qt.PenStyle.NoPen)
        scale = self._pulse_scale
        scaled_r = int(r * scale)
        cy_bounce = cy + int(self._bounce_y)
        p.drawEllipse(cx - scaled_r, cy_bounce - scaled_r,
                      scaled_r * 2, scaled_r * 2)

        # ── Glow ring ─────────────────────────────────────────────────────
        glow_color = {
            AvatarState.IDLE:      QColor(100, 100, 255, 60),
            AvatarState.LISTENING: QColor(30, 144, 255, 100),
            AvatarState.THINKING:  QColor(255, 165, 0, 100),
            AvatarState.SPEAKING:  QColor(50, 205, 50, 100),
            AvatarState.ERROR:     QColor(255, 50, 50, 100),
        }.get(self.state, QColor(100, 100, 255, 60))

        p.setPen(QPen(glow_color, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - scaled_r - 4, cy_bounce - scaled_r - 4,
                      (scaled_r + 4) * 2, (scaled_r + 4) * 2)

        # ── State-specific inner animation ─────────────────────────────────
        if self.state == AvatarState.IDLE:
            # Soft glowing dot
            inner = QColor(150, 150, 255, 180)
            p.setBrush(QBrush(inner))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - 8, cy_bounce - 8, 16, 16)

        elif self.state == AvatarState.LISTENING:
            # Waveform bars
            bar_w = 7
            n = len(self._wave_bars)
            total_w = n * bar_w + (n - 1) * 3
            start_x = cx - total_w // 2
            p.setPen(Qt.PenStyle.NoPen)
            for i, h in enumerate(self._wave_bars):
                bar_h = int(h * 48)
                color = QColor(30, 144, 255, 220)
                p.setBrush(QBrush(color))
                bx = start_x + i * (bar_w + 3)
                by = cy_bounce - bar_h // 2
                p.drawRoundedRect(bx, by, bar_w, bar_h, 2, 2)

        elif self.state == AvatarState.THINKING:
            # Spinning arcs
            p.setPen(QPen(QColor(255, 165, 0, 200), 3,
                          Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRect(cx - 32, cy_bounce - 32, 64, 64)
            p.drawArc(rect, int(self._spin_angle) * 16, 120 * 16)
            p.setPen(QPen(QColor(255, 200, 50, 150), 2,
                          Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(rect,
                      int(self._spin_angle + 180) * 16, 80 * 16)

        elif self.state == AvatarState.SPEAKING:
            # Speaking indicator
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(50, 205, 50, 200)))
            for i in range(3):
                angle = math.radians(self._spin_angle + i * 120)
                dx = int(22 * math.cos(angle))
                dy = int(22 * math.sin(angle))
                p.drawEllipse(cx + dx - 6, cy_bounce + dy - 6, 12, 12)

        # ── Text labels ────────────────────────────────────────────────────
        if self._text:
            p.setPen(QColor(220, 220, 255, 230))
            font = QFont("Sans", 8, QFont.Weight.Bold)
            p.setFont(font)
            p.drawText(QRect(0, 210, 240, 22),
                       Qt.AlignmentFlag.AlignCenter, self._text)

        if self._subtext:
            p.setPen(QColor(160, 160, 200, 180))
            font2 = QFont("Sans", 7)
            p.setFont(font2)
            p.drawText(QRect(0, 232, 240, 18),
                       Qt.AlignmentFlag.AlignCenter,
                       self._subtext[:25])

        # ── State label ────────────────────────────────────────────────────
        state_labels = {
            AvatarState.IDLE:      "FLASH",
            AvatarState.LISTENING: "LISTENING",
            AvatarState.THINKING:  "THINKING",
            AvatarState.SPEAKING:  "SPEAKING",
            AvatarState.ERROR:     "ERROR",
        }
        p.setPen(QColor(120, 120, 180, 200))
        font3 = QFont("Sans", 6)
        p.setFont(font3)
        p.drawText(QRect(0, 252, 240, 16),
                   Qt.AlignmentFlag.AlignCenter,
                   state_labels.get(self.state, ""))

    def mousePressEvent(self, event):
        # Allow dragging the orb
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_pos') and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Flash Mode", lambda: None)
        menu.addSeparator()
        menu.addAction("Exit", QApplication.quit)
        menu.exec(event.globalPos())


# ══════════════════════════════════════════════════════════════════════════════
#  CHAT WINDOW — proper text mode with full conversation display
# ══════════════════════════════════════════════════════════════════════════════
class ChatWindow(QWidget):
    """
    A floating, always-on-top chat window.
    Shows full conversation. Has text input. Hotkey to toggle.
    Flash types its responses here AND speaks them.
    """
    send_text = pyqtSignal(str)   # user typed something

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible = False
        self._setup_ui()
        self._setup_window()

    def _setup_window(self):
        self.setWindowTitle("Flash Copilot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = 420, 520
        self.setFixedWidth(w)
        self.setMinimumHeight(300)
        self.resize(w, h)
        self.move(screen.width() - w - 20,
                  screen.height() - h - 60)

    def _setup_ui(self):
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Title bar ────────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(
            "background: #1a1a2e; border-radius: 0px;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 0, 8, 0)

        self._title_label = QLabel("⚡ Flash Copilot")
        self._title_label.setStyleSheet(
            "color: #a0a0ff; font-size: 12px; font-weight: bold;")

        self._status_label = QLabel("ready")
        self._status_label.setStyleSheet(
            "color: #505070; font-size: 10px;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "QPushButton{background:#2a2a3e;color:#707090;border:none;"
            "border-radius:3px;font-size:11px;}"
            "QPushButton:hover{background:#3a3a5e;color:#ffffff;}")
        close_btn.clicked.connect(self.hide_window)

        tb_layout.addWidget(self._title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self._status_label)
        tb_layout.addSpacing(6)
        tb_layout.addWidget(close_btn)

        # ── Chat display ──────────────────────────────────────────────────
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setStyleSheet("""
            QTextEdit {
                background: #0d0d1a;
                color: #d0d0e8;
                border: none;
                font-family: 'Noto Sans', 'Ubuntu', sans-serif;
                font-size: 13px;
                padding: 12px;
                selection-background-color: #3a3a6e;
            }
            QScrollBar:vertical {
                background: #0d0d1a; width: 6px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #3a3a6e; border-radius: 3px; min-height: 20px;
            }
        """)
        self._chat.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        # ── Input area ────────────────────────────────────────────────────
        input_frame = QWidget()
        input_frame.setStyleSheet("background: #12122a;")
        input_frame.setFixedHeight(52)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Type a command or question… (Enter to send)")
        self._input.setStyleSheet("""
            QLineEdit {
                background: #1e1e3a;
                color: #d0d0e8;
                border: 1px solid #3a3a6e;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #6060c0; }
        """)
        self._input.returnPressed.connect(self._on_send)

        send_btn = QPushButton("↑")
        send_btn.setFixedSize(34, 34)
        send_btn.setStyleSheet("""
            QPushButton {
                background: #3a3aaa;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover { background: #5050cc; }
            QPushButton:pressed { background: #2a2a88; }
        """)
        send_btn.clicked.connect(self._on_send)

        input_layout.addWidget(self._input)
        input_layout.addWidget(send_btn)

        # ── Hint bar ──────────────────────────────────────────────────────
        hint = QLabel(
            "Hold Right Ctrl to speak  ·  Ctrl+Space to toggle this window")
        hint.setStyleSheet(
            "background:#0a0a18;color:#404060;font-size:10px;"
            "padding:3px 12px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title_bar)
        layout.addWidget(self._chat, 1)
        layout.addWidget(input_frame)
        layout.addWidget(hint)

        # Drag support
        self._drag_pos = None

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.add_user_message(text)
        self.send_text.emit(text)

    def add_user_message(self, text: str):
        self._chat.append(
            f'<p style="color:#8888ff;margin:4px 0">'
            f'<b>You:</b> {text}</p>'
        )
        self._scroll_to_bottom()

    def add_flash_message(self, text: str, is_action: bool = False):
        color = "#50c878" if not is_action else "#ffaa44"
        label = "Flash" if not is_action else "Flash →"
        # Clean markdown for display
        display = text.replace('<', '&lt;').replace('>', '&gt;')
        self._chat.append(
            f'<p style="color:{color};margin:4px 0">'
            f'<b>{label}:</b> {display}</p>'
        )
        self._scroll_to_bottom()

    def add_system_message(self, text: str):
        self._chat.append(
            f'<p style="color:#606080;font-size:11px;margin:2px 0">'
            f'<i>{text}</i></p>'
        )
        self._scroll_to_bottom()

    def set_status(self, status: str, color: str = "#505070"):
        self._status_label.setText(status)
        self._status_label.setStyleSheet(
            f"color: {color}; font-size: 10px;")

    def _scroll_to_bottom(self):
        cursor = self._chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._chat.setTextCursor(cursor)

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()
        self._visible = True

    def hide_window(self):
        self.hide()
        self._visible = False

    def toggle(self):
        if self._visible:
            self.hide_window()
        else:
            self.show_window()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None



# ══════════════════════════════════════════════════════════════════════════════
#  WORKER THREAD — processes voice commands without blocking UI
# ══════════════════════════════════════════════════════════════════════════════
class WorkerThread(QThread):
    state_changed  = pyqtSignal(str, str, str)   # state, text, subtext
    speak_signal   = pyqtSignal(str)
    notify_signal  = pyqtSignal(str, str)        # title, message
    confirm_signal = pyqtSignal(str, str)        # command, explanation
    chat_message   = pyqtSignal(str, bool)       # text, is_action

    def __init__(self, brain, voice, desktop, memory, safety):
        super().__init__()
        self.brain   = brain
        self.voice   = voice
        self.desktop = desktop
        self.memory  = memory
        self.safety  = safety
        self._queue  = queue.Queue()
        self._running = True

    def enqueue(self, text: str):
        self._queue.put(text)

    def stop(self):
        self._running = False
        self._queue.put(None)

    def run(self):
        while self._running:
            try:
                user_input = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if user_input is None:
                break

            self._process(user_input)

    def _process(self, user_input: str):
        log.info(f"Processing: {user_input}")

        # Think
        self.state_changed.emit(AvatarState.THINKING, "Thinking...", user_input[:30])

        # Only recall memory for conversational/complex queries
        # Skip for obvious commands (play X, open X, etc.) — reduces hallucination
        simple_cmd = bool(self.brain.router.match(user_input) if hasattr(self.brain, 'router') else None)
        mem_context = '' if simple_cmd else self.memory.recall(user_input)

        # Get LLM response with tools
        response, tool_calls = self.brain.think(user_input, mem_context)

        # Execute any tool calls
        tool_outputs = []
        for tool in tool_calls:
            result = self._execute_tool(tool)
            if result:
                tool_outputs.append(result)
                # Inject result into brain history so next turn has context
                self.brain.inject_tool_result(tool.get('action', tool.get('name','tool')), result)

        # If tools ran — use their output for final reply
        if tool_outputs:
            # For simple actions (open URL, run cmd) — just use initial response
            # Only synthesize if there's actual data to report
            has_data = any(len(o) > 60 for o in tool_outputs)
            if has_data:
                final_reply = self.brain.synthesize(
                    user_input, response, tool_outputs
                )
            else:
                # Simple action — use initial spoken reply
                final_reply = response or "Done."
        else:
            final_reply = response

        # Only save meaningful exchanges to memory (skip simple open/play/run)
        meaningful = not simple_cmd and len(user_input.split()) > 4
        if meaningful:
            self.memory.save(user_input, final_reply)

        # Emit to chat window and speak
        self.state_changed.emit(AvatarState.SPEAKING, "Speaking", "")
        has_tools = len(tool_outputs) > 0
        self.chat_message.emit(final_reply, has_tools)
        self.speak_signal.emit(final_reply)

    def _execute_tool(self, tool: dict) -> Optional[str]:
        # Handle both formats:
        # Brain v5: {'name': 'open_url', 'args': {'url': '...'}}
        # Brain v6: {'action': 'open_url', 'url': '...'}
        if 'action' in tool:
            name = tool.get('action', '')
            # args are the remaining keys minus 'action'
            args = {k: v for k, v in tool.items() if k != 'action'}
        else:
            name = tool.get('name', '')
            args = tool.get('args', {})

        try:
            if name == 'run_command':
                cmd = args.get('command', args.get('value', ''))
                if not cmd and isinstance(args, str):
                    cmd = args
                if not cmd:
                    return "No command specified."
                needs_confirm = self.safety.needs_confirmation(cmd)
                if needs_confirm:
                    approved = self.safety.confirm_sync(cmd)
                    if not approved:
                        return f"Cancelled: {cmd}"
                out, err = self.desktop.run_command(cmd)
                return out or err or f"Command ran: {cmd}"

            elif name == 'open_app':
                app = args.get('app', args.get('value', ''))
                if app:
                    self.desktop.open_application(app)
                    return f"Opened {app}"
                return "No app specified."

            elif name == 'web_search':
                query = args.get('query', '')
                results = self.desktop.web_search(query)
                return f"Search results for '{query}':\n{results}"

            elif name == 'open_url':
                # v6 flat: args={'url':'...'}, v5 nested: args={'url':'...'}
                url = args.get('url', args.get('value', ''))
                if url:
                    self.desktop.open_url(url)
                    return f"Opened: {url}"
                return "No URL specified."

            elif name == 'open_url_and_type':
                if isinstance(args, dict):
                    url   = args.get('url', '')
                    query = args.get('query', '')
                else:
                    return "Missing args for open_url_and_type"
                if url and query:
                    return self.desktop.open_url_and_type(url, query)
                elif url:
                    self.desktop.open_url(url)
                    return f"Opened: {url}"
                return "No URL specified."

            elif name == 'read_file':
                path = args.get('path', '')
                content = self.desktop.read_file(path)
                return f"File contents:\n{content}"

            elif name == 'type_text':
                text = args.get('text', '')
                self.desktop.type_text(text)
                return f"Typed: {text}"

            elif name == 'take_screenshot':
                path = self.desktop.take_screenshot()
                return f'Screenshot: {path}'

            elif name in ('get_system_info', 'system_info'):
                return self.desktop.get_system_info()

            elif name == 'get_weather':
                return self.desktop.get_weather_summary()

            elif name == 'weather_activity':
                if isinstance(args, dict):
                    activity = args.get('activity', 'going outside')
                else:
                    activity = 'going outside'
                return self.desktop.is_good_for_activity(activity)

            elif name == 'get_time':
                return self.desktop.get_current_time()

            elif name == 'read_screen':
                return self.desktop.read_screen()

            elif name == 'get_clipboard':
                clip = self.desktop.get_clipboard()
                return clip if clip else "Clipboard is empty."

            elif name == 'check_logs':
                n = args.get('lines', 50)
                service = args.get('service', '')
                logs = self.desktop.get_logs(service, n)
                return logs

            elif name == 'create_file':
                path = args.get('path', args.get('value', '~/untitled.txt'))
                content_text = args.get('content', '')
                import os
                full_path = os.path.expanduser(path)
                with open(full_path, 'w') as f:
                    f.write(content_text)
                return f"Created: {full_path}"

            elif name == 'open_url_and_type':
                url   = args.get('url', '')
                query = args.get('query', '')
                if url and query:
                    return self.desktop.open_url_and_type(url, query)
                elif url:
                    self.desktop.open_url(url)
                    return f"Opened: {url}"
                return "Missing URL."

            elif name == 'clipboard_get':
                import subprocess as sp
                for cmd in [['xclip','-selection','clipboard','-o'],
                             ['xsel','--clipboard','--output']]:
                    try:
                        r = sp.run(cmd, capture_output=True, text=True, timeout=3)
                        if r.returncode == 0:
                            return f"Clipboard: {r.stdout.strip()[:500]}"
                    except Exception:
                        pass
                return "Clipboard: could not read"

            elif name == 'active_window':
                import subprocess as sp
                try:
                    r = sp.run(['xdotool','getactivewindow','getwindowname'],
                               capture_output=True, text=True, timeout=3)
                    return f"Active window: {r.stdout.strip()}"
                except Exception:
                    return "Active window: unknown"

            elif name == 'keyboard_shortcut':
                keys = args.get('keys', args.get('key', ''))
                return self.desktop.keyboard_shortcut(keys)

            elif name == 'click_play':
                return self.desktop.click_play()

            elif name == 'vscode_file':
                return self.desktop.vscode_file()

            elif name == 'read_screen':
                text = self.desktop.read_screen()
                if len(text) > 300:
                    return self.brain.synthesize('screen content', text, [text])
                return text

            elif name == 'type_text':
                self.desktop.type_text(args.get('text', ''))
                return 'Typed text.'

            elif name == 'play_youtube':
                query = args.get('query', '')
                if query:
                    return self.desktop.play_youtube(query)
                return "No query for play_youtube."

            elif name == 'keyboard_shortcut':
                keys = args.get('keys', '')
                return self.desktop.keyboard_shortcut(keys)

            elif name == 'click_play':
                return self.desktop.click_play()

            elif name == 'vscode_file':
                return self.desktop.vscode_file()

            elif name == 'get_active_window':
                return self.desktop.get_active_window()

            elif name == 'read_screen':
                return self.desktop.read_screen()

            elif name == 'type_text':
                self.desktop.type_text(args.get('text', ''))
                return f"Typed text."

            else:
                return None

        except Exception as e:
            log.error(f"Tool {name} failed: {e}")
            return f"Error executing {name}: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM TRAY
# ══════════════════════════════════════════════════════════════════════════════
class TrayIcon(QSystemTrayIcon):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self.app_ref = app_ref
        self._create_icon()
        self._create_menu()
        self.activated.connect(self._on_activated)

    def _create_icon(self):
        # Create a simple colored icon programmatically
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(80, 80, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, 28, 28)
        p.setPen(QColor(255, 255, 255))
        font = QFont("Sans", 10, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRect(0, 0, 32, 32), Qt.AlignmentFlag.AlignCenter, "F")
        p.end()
        self.setIcon(QIcon(pix))
        self.setToolTip(f"{self.app_ref.brain.assistant_name} — Online")

    def _create_menu(self):
        menu = QMenu()
        menu.addAction("Show Avatar",
                       lambda: self.app_ref.avatar.show())
        menu.addAction("Hide Avatar",
                       lambda: self.app_ref.avatar.hide())
        menu.addSeparator()
        menu.addAction("Chat Window  (Ctrl+Space)",
                       self.app_ref.toggle_text_mode)
        menu.addSeparator()
        menu.addAction("Settings", self.app_ref.open_settings)
        menu.addAction("Exit", QApplication.quit)
        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.app_ref.avatar.isVisible():
                self.app_ref.avatar.hide()
            else:
                self.app_ref.avatar.show()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════
class FlashCopilot(QObject):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config

        # Load config
        self.model_name = config.get('model', 'qwen2.5-coder:3b')
        self.voice_model = config.get('voice', 'en_US-ryan-high')
        self.hotkey = config.get('hotkey', 'ctrl_r')
        self.voices_dir = Path(config.get('voices_dir',
                               str(PROJECT_DIR / 'voices')))

        # Initialize subsystems
        log.info("Initializing Flash Copilot subsystems...")

        self.memory  = MemoryEngine(PROJECT_DIR / 'data' / 'memory')
        self.safety  = SafetyLayer()
        self.desktop = DesktopControl()                    # init first
        self.brain   = Brain(model=self.model_name,
                             desktop=self.desktop)         # inject desktop
        self.voice   = VoiceEngine(
            voices_dir=self.voices_dir,
            voice_model=self.voice_model
        )
        self.hotkey_listener = HotkeyListener(
            hotkey=self.hotkey,
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release
        )

        # Proactive monitor
        self.monitor = ProactiveMonitor(
            alert_callback=self._on_proactive_alert
        )

        # Plugin system
        self.plugins = PluginLoader(PROJECT_DIR / 'plugins')
        if self.plugins.names:
            log.info(f"Plugins loaded: {self.plugins.names}")

        log.info("All subsystems ready.")

    def launch_ui(self):
        """Launch the Qt UI components."""
        self.avatar = AvatarWidget()
        self.avatar.show()
        self.avatar.raise_()

        # Chat window (text mode)
        self.chat_win = ChatWindow()
        self.chat_win.send_text.connect(self._on_chat_input)
        # Ctrl+Space shortcut to toggle chat window
        self._chat_shortcut = QShortcut(
            QKeySequence("Ctrl+Space"), self.avatar)
        self._chat_shortcut.activated.connect(self.chat_win.toggle)

        self.tray = TrayIcon(self)
        self.tray.show()

        # Worker thread
        self.worker = WorkerThread(
            self.brain, self.voice,
            self.desktop, self.memory, self.safety
        )
        self.worker.state_changed.connect(self._on_state_changed)
        self.worker.speak_signal.connect(self._on_speak)
        self.worker.notify_signal.connect(self._on_notify)
        self.worker.chat_message.connect(self._on_chat_message)
        self.worker.start()

        # Start hotkey listener and proactive monitor
        self.hotkey_listener.start()
        self.monitor.start()

        log.info("Flash Copilot UI launched.")
        self.avatar.set_state(AvatarState.IDLE, "FLASH", "Ready")
        self.chat_win.add_system_message(
            f"Flash online — {self.brain.assistant_name} ready for {self.brain.user_name}"
        )

    def _on_hotkey_press(self):
        """PTT pressed — interrupts any ongoing speech, starts recording."""
        log.info("PTT key pressed — starting recording")
        # Stop any ongoing TTS immediately
        self.voice.interrupt()  # kills TTS, waits 300ms internally
        self.avatar.set_state(AvatarState.LISTENING, "LISTENING", "Speak now...")
        self.voice.start_recording()

    def _on_hotkey_release(self):
        """Called when user releases the PTT hotkey."""
        log.info("PTT key released — processing audio")
        audio_data = self.voice.stop_recording()

        if audio_data is None or len(audio_data) < 1000:
            self.avatar.set_state(AvatarState.IDLE, "FLASH", "Ready")
            return

        # Transcribe in background
        def transcribe_and_enqueue():
            text = self.voice.transcribe(audio_data)
            if text and len(text.strip()) > 2:
                log.info(f"Transcribed: {text}")
                self.avatar.set_state(AvatarState.THINKING, "Thinking...",
                                      text[:30])
                self.tray.showMessage(
                    "Flash heard you:",
                    text,
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                self.chat_win.add_user_message(text)
                self.worker.enqueue(text)
            else:
                self.avatar.set_state(AvatarState.IDLE, "FLASH", "Ready")

        threading.Thread(target=transcribe_and_enqueue, daemon=True).start()

    def _on_state_changed(self, state: str, text: str, subtext: str):
        self.avatar.set_state(state, text, subtext)

    def _on_speak(self, text: str):
        """Format text for TTS then speak it."""
        def _do_speak():
            # Always format before speaking — never raw data to TTS
            tts_text = _format_for_speech(text)
            if not tts_text:
                self.avatar.set_state(AvatarState.IDLE, "FLASH", "Ready")
                return
            self.voice.speak(tts_text)
            self.avatar.set_state(AvatarState.IDLE, "FLASH", "Ready")
        threading.Thread(target=_do_speak, daemon=True).start()

    def _on_notify(self, title: str, message: str):
        self.tray.showMessage(
            title, message,
            QSystemTrayIcon.MessageIcon.Information, 3000
        )

    def _on_chat_message(self, text: str, is_action: bool):
        """Flash reply goes to chat window."""
        self.chat_win.add_flash_message(text, is_action)

    def _on_chat_input(self, text: str):
        """User typed in chat window."""
        self.avatar.set_state(AvatarState.THINKING, "Thinking...", text[:30])
        self.worker.enqueue(text)

    def _on_proactive_alert(self, message: str):
        """Proactive monitor alert."""
        log.info(f"Proactive alert: {message}")
        self.chat_win.add_system_message(f"Alert: {message}")
        self.tray.showMessage(
            "Flash Alert", message,
            QSystemTrayIcon.MessageIcon.Warning, 5000
        )
        threading.Thread(
            target=self.voice.speak, args=(message,), daemon=True
        ).start()


    def toggle_text_mode(self):
        """Toggle the chat window."""
        self.chat_win.toggle()

    def open_settings(self):
        """Open settings dialog."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            None,
            "Flash Copilot Settings",
            f"Current configuration:\n\n"
            f"Model:   {self.model_name}\n"
            f"Voice:   {self.voice_model}\n"
            f"Hotkey:  {self.hotkey}\n\n"
            f"Edit: {PROJECT_DIR}/config/config.json"
        )

    def shutdown(self):
        log.info("Shutting down Flash Copilot...")
        self.hotkey_listener.stop()
        self.monitor.stop()
        self.worker.stop()
        self.worker.wait()
        log.info("Shutdown complete.")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    config_path = PROJECT_DIR / 'config' / 'config.json'
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)

    # Defaults
    model_file = PROJECT_DIR / 'config' / 'model.txt'
    voice_file = PROJECT_DIR / 'config' / 'voice.txt'

    model = model_file.read_text().strip() if model_file.exists() \
            else 'qwen2.5-coder:3b'
    voice = voice_file.read_text().strip() if voice_file.exists() \
            else 'en_US-ryan-high'

    return {
        'model': model,
        'voice': voice,
        'hotkey': 'ctrl_r',        # Right Ctrl = push to talk
        'voices_dir': str(PROJECT_DIR / 'voices'),
        'data_dir': str(PROJECT_DIR / 'data'),
    }


def run_test():
    """Quick smoke test without launching Qt."""
    print("\n🔬 Running Flash Copilot diagnostics...\n")

    # Test Ollama
    print("Testing Ollama...", end=' ', flush=True)
    try:
        import requests
        r = requests.get('http://localhost:11434', timeout=3)
        print("✓ Online")
    except Exception as e:
        print(f"✗ FAILED: {e}")

    # Test Whisper
    print("Testing Whisper...", end=' ', flush=True)
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel('tiny', device='cpu', compute_type='int8')
        print("✓ Loaded")
    except Exception as e:
        print(f"✗ FAILED: {e}")

    # Test Piper
    print("Testing Piper TTS...", end=' ', flush=True)
    voices_dir = PROJECT_DIR / 'voices'
    onnx_files = list(voices_dir.glob('*.onnx'))
    if onnx_files:
        print(f"✓ {len(onnx_files)} voice(s) found")
    else:
        print("✗ No voice models in voices/ dir")

    # Test PyAutoGUI (desktop control)
    print("Testing xdotool...", end=' ', flush=True)
    result = subprocess.run(['which', 'xdotool'],
                           capture_output=True, text=True)
    if result.returncode == 0:
        print("✓ Available")
    else:
        print("✗ Not found (install with: sudo apt install xdotool)")

    print("\n✅ Diagnostics complete.\n")


def main():
    parser = argparse.ArgumentParser(description='Flash Copilot')
    parser.add_argument('--test', action='store_true',
                        help='Run diagnostics and exit')
    parser.add_argument('--tray', action='store_true',
                        help='Start minimized to tray')
    parser.add_argument('--model', default=None,
                        help='Override model name')
    parser.add_argument('--hotkey', default=None,
                        help='Override hotkey (e.g. ctrl_r, scroll_lock)')
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    config = load_config()
    if args.model:
        config['model'] = args.model
    if args.hotkey:
        config['hotkey'] = args.hotkey

    # Create data directory
    Path(config.get('data_dir', str(PROJECT_DIR / 'data'))).mkdir(
        parents=True, exist_ok=True
    )

    # Launch Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Flash Copilot")
    app.setQuitOnLastWindowClosed(False)

    # Check for system tray support
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("WARNING: System tray not available.")

    copilot = FlashCopilot(config)
    copilot.launch_ui()

    if args.tray:
        copilot.avatar.hide()

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda *_: (copilot.shutdown(), app.quit()))

    sys.exit(app.exec())


if __name__ == '__main__':
    main()