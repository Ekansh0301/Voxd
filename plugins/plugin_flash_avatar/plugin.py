#!/usr/bin/env python3
"""
plugins/plugin_flash_avatar/plugin.py
================================================================================
PyGPT Plugin: Flash Avatar Overlay
================================================================================
Adds an animated floating orb to PyGPT.
Reacts to AI states: idle → listening → thinking → speaking.
Always-on-top, draggable, lives in screen corner.

Install:
  1. Copy to ~/.config/pygpt-net/plugins/plugin_flash_avatar/
  2. Restart PyGPT
  3. Enable in Plugins menu

================================================================================
"""

import math

try:
    from PyQt6.QtCore import QRect, Qt, QTimer
    from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
    from PyQt6.QtWidgets import QApplication, QMenu, QWidget
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

try:
    from pygpt_net.core.dispatcher import Event
    from pygpt_net.plugin.base import BasePlugin
except ImportError:
    class BasePlugin:
        def __init__(self):
            self.id = ""
            self.name = ""
            self.description = ""
            self.options = {}
        def add_option(self, *args, **kwargs): pass
    class Event:
        pass


PLUGIN_ID = "plugin_flash_avatar"


class AvatarOrb(QWidget):
    """The floating animated orb."""

    def __init__(self):
        super().__init__()
        self.state = 'idle'
        self._tick = 0.0
        self._wave = [0.0] * 10
        self._spin = 0.0
        self._drag_pos = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(120, 140)

        # Position bottom-right
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 140, screen.height() - 160)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(33)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def _animate(self):
        self._tick += 0.06
        self._spin = (self._spin + 4) % 360

        if self.state == 'listening':
            for i in range(len(self._wave)):
                t = abs(math.sin(self._tick * 3.5 + i * 0.6))
                self._wave[i] += (t - self._wave[i]) * 0.35

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = 60, 60, 38

        # Colors per state
        colors = {
            'idle':      (QColor(15, 15, 35, 210), QColor(80, 80, 220, 80)),
            'listening': (QColor(5, 20, 50, 220),  QColor(30, 144, 255, 110)),
            'thinking':  (QColor(30, 18, 5, 215),  QColor(255, 165, 0, 110)),
            'speaking':  (QColor(5, 30, 12, 215),  QColor(50, 205, 50, 110)),
            'error':     (QColor(40, 5, 5, 215),   QColor(255, 50, 50, 110)),
        }
        bg_col, glow_col = colors.get(self.state, colors['idle'])

        # Pulse for idle and speaking
        scale = 1.0
        if self.state in ('idle', 'speaking'):
            scale = 1.0 + 0.06 * abs(math.sin(self._tick * 0.9))

        sr = int(r * scale)

        # Main orb
        p.setBrush(QBrush(bg_col))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - sr, cy - sr, sr * 2, sr * 2)

        # Glow ring
        p.setPen(QPen(glow_col, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - sr - 3, cy - sr - 3,
                      (sr + 3) * 2, (sr + 3) * 2)

        # Inner animation
        if self.state == 'idle':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(120, 120, 255, 160)))
            p.drawEllipse(cx - 6, cy - 6, 12, 12)

        elif self.state == 'listening':
            p.setPen(Qt.PenStyle.NoPen)
            bw = 4
            n = len(self._wave)
            total = n * bw + (n - 1) * 2
            sx = cx - total // 2
            for i, h in enumerate(self._wave):
                bh = int(h * 26)
                p.setBrush(QBrush(QColor(30, 144, 255, 220)))
                p.drawRoundedRect(sx + i * (bw + 2),
                                   cy - bh // 2, bw, bh, 1, 1)

        elif self.state == 'thinking':
            p.setPen(QPen(QColor(255, 165, 0, 200), 2.5,
                          Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRect(cx - 18, cy - 18, 36, 36),
                      int(self._spin) * 16, 110 * 16)

        elif self.state == 'speaking':
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                a = math.radians(self._spin + i * 120)
                dx, dy = int(13 * math.cos(a)), int(13 * math.sin(a))
                p.setBrush(QBrush(QColor(50, 205, 50, 200)))
                p.drawEllipse(cx + dx - 3, cy + dy - 3, 6, 6)

        # State label
        labels = {
            'idle': 'FLASH', 'listening': 'MIC',
            'thinking': 'THINK', 'speaking': 'SPEAK',
        }
        p.setPen(QColor(160, 160, 220, 200))
        p.setFont(QFont("Sans", 6))
        p.drawText(QRect(0, 108, 120, 14),
                   Qt.AlignmentFlag.AlignCenter,
                   labels.get(self.state, ''))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction("Hide", self.hide)
        m.addAction("Exit", QApplication.quit)
        m.exec(e.globalPos())


class Plugin(BasePlugin):
    """PyGPT Avatar Overlay Plugin."""

    def __init__(self):
        super().__init__()
        self.id = PLUGIN_ID
        self.name = "Flash Avatar Overlay"
        self.description = "Animated orb that reacts to AI state changes."
        self._orb = None
        self._orb_thread = None

        self.add_option(
            "enabled",
            type="bool",
            value=True,
            label="Show avatar orb",
            description="Display animated orb in screen corner",
        )
        self.add_option(
            "position",
            type="combo",
            value="bottom-right",
            label="Orb position",
            description="Screen corner for the avatar orb",
            keys=["bottom-right", "bottom-left", "top-right", "top-left"],
        )

    def setup(self):
        return self.options

    def attach(self, window):
        self.window = window
        if HAVE_QT and self.get_option_value("enabled"):
            self._launch_orb()

    def _launch_orb(self):
        """Create orb widget on Qt main thread."""
        try:
            self._orb = AvatarOrb()
            self._orb.show()
        except Exception as e:
            print(f"[FlashAvatar] Could not create orb: {e}")

    def handle(self, event: Event, *args, **kwargs):
        if self._orb is None:
            return

        # Map PyGPT events to avatar states
        name = getattr(event, 'name', '')

        if 'input' in name and 'audio' in name:
            self._orb.set_state('listening')
        elif 'generate' in name or 'processing' in name:
            self._orb.set_state('thinking')
        elif 'response' in name or 'audio_output' in name:
            self._orb.set_state('speaking')
        elif 'done' in name or 'ready' in name or 'idle' in name:
            self._orb.set_state('idle')
        elif 'error' in name:
            self._orb.set_state('error')

    def get_option_value(self, key: str):
        opt = self.options.get(key, {})
        return opt.get('value', opt.get('default', ''))
