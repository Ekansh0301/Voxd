"""
The avatar window: a transparent, always-on-top Live2D overlay.

    TARS_WS=ws://127.0.0.1:8765/?token=... .venv/bin/python -m tars.ui

Normally started by `python -m tars.voice`. Runs under XWayland, because
GNOME's Wayland compositor doesn't let native apps stay on top or choose
their position. Drag it with the left mouse button; right-click for options.
Under the avatar: subtitles (what you said, what TARS is saying) and a box to
type to TARS instead of talking. A TARS icon in the top bar has the same menu.

The page is served through a private tars:// scheme instead of file:// (whose
URLs Chromium's fetch() refuses), so no network port is opened for it:
  tars://app/...     the built avatar app  (~/.local/share/tars/avatar/app)
  tars://avatar/...  Cubism Core + model    (~/.local/share/tars/avatar)
"""

import argparse
import mimetypes
import os
import signal
import sys
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # XWayland: always-on-top + positioning

import json

from PyQt6.QtCore import QBuffer, QByteArray, QEvent, QObject, QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from tars import TARS_HOME

AVATAR = TARS_HOME / "avatar"
ROOTS = {"app": AVATAR / "app", "avatar": AVATAR}
SCHEME = b"tars"


def register_scheme():
    """Must run before QApplication exists."""
    s = QWebEngineUrlScheme(SCHEME)
    s.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    F = QWebEngineUrlScheme.Flag
    s.setFlags(F.SecureScheme | F.LocalAccessAllowed | F.CorsEnabled | F.FetchApiAllowed)
    QWebEngineUrlScheme.registerScheme(s)


def resolve_asset(
    host: str, path: str, roots: dict[str, Path] = ROOTS, base: Path = TARS_HOME
) -> Path | None:
    """File for tars://<host>/<path>, or None if unknown or outside TARS's data dir."""
    root = roots.get(host)
    if root is None:
        return None
    target = (root / path.lstrip("/")).resolve()
    # resolve() follows the model symlink, which also points inside the data dir
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        return None
    return target


class FileScheme(QWebEngineUrlSchemeHandler):
    """Serves files under ROOTS; anything outside them is refused."""

    def requestStarted(self, job: QWebEngineUrlRequestJob | None):
        if job is None:
            return
        url = job.requestUrl()
        path = resolve_asset(url.host(), url.path())
        if path is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        buf = QBuffer(parent=job)
        buf.setData(QByteArray(path.read_bytes()))
        job.reply(mime.encode(), buf)


class Page(QWebEnginePage):
    """Prints page console messages with their source location."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        print(
            f"js [{Path(QUrl(source).path()).name}:{line}] {message}", file=sys.stderr, flush=True
        )


class DragFilter(QObject):
    """Left-drag anywhere moves the window; clicks still reach the page."""

    def __init__(self, window):
        super().__init__()
        self.window, self.offset = window, None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self.offset = ev.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
        elif t == QEvent.Type.MouseMove and self.offset is not None:
            self.window.move(ev.globalPosition().toPoint() - self.offset)
        elif t == QEvent.Type.MouseButtonRelease:
            self.offset = None
        return False


def main():
    # Ctrl+C in the terminal reaches this child too; exit quietly (TARS shuts it down anyway).
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ws",
        default=os.environ.get("TARS_WS"),
        help="avatar bus URL (with token); default $TARS_WS",
    )
    ap.add_argument("--size", default="320x420", help="window WIDTHxHEIGHT")
    ap.add_argument("--zoom", type=float, default=2.2, help="1 = full body; larger = closer")
    ap.add_argument("--y", type=float, default=-1.1, help="vertical offset of the model")
    ap.add_argument("--snapshot", help="testing: save PNGs of the window to this prefix")
    ap.add_argument("--snapshot-at", default="6,9,12,15", help="seconds after start")
    args = ap.parse_args()
    if not args.ws:
        sys.exit("no avatar bus: start TARS with `tars` (or pass --ws)")
    if not (ROOTS["app"] / "index.html").exists():
        sys.exit("avatar app not built: run `.venv/bin/python -m tars.ui.live2d.build`")

    register_scheme()
    app = QApplication(sys.argv)
    app.setApplicationName("TARS")
    app.setDesktopFileName("org.tars.TARS")  # GNOME shows TARS's icon for its windows
    handler = FileScheme()
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(SCHEME, handler)

    view = QWebEngineView()
    view.setPage(Page(view))
    view.setWindowTitle("TARS")
    view.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool  # no taskbar entry
    )
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    view.page().setBackgroundColor(QColor(0, 0, 0, 0))
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

    w, h = (int(x) for x in args.size.split("x"))
    view.setFixedSize(w, h)
    view.load(
        QUrl(f"tars://app/index.html?ws={quote(args.ws, safe='')}&zoom={args.zoom}&y={args.y}")
    )

    # The window: avatar, then subtitles, then the text box.
    win = QWidget()
    win.setWindowTitle("TARS")
    win.setWindowFlags(view.windowFlags())
    view.setWindowFlags(Qt.WindowType.Widget)
    win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    layout = QVBoxLayout(win)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(view)
    caption = QLabel()
    caption.setWordWrap(True)
    caption.setTextFormat(Qt.TextFormat.RichText)
    caption.setFixedWidth(w)
    caption.setStyleSheet(
        "QLabel { background: rgba(14, 18, 32, 215); color: #f2f4f8; border-radius: 10px;"
        " padding: 7px 10px; font-size: 13px; }"
    )
    caption.hide()
    layout.addWidget(caption)
    entry = QLineEdit()
    entry.setPlaceholderText("Type to TARS…  (Enter to send)")
    entry.setFixedWidth(w)
    entry.setStyleSheet(
        "QLineEdit { background: rgba(14, 18, 32, 215); color: #f2f4f8; border: 1px solid #3a4560;"
        " border-radius: 10px; padding: 6px 10px; font-size: 13px; }"
    )
    layout.addWidget(entry)

    def fit():
        """Resize to the caption, growing upward: the bottom edge stays put."""
        bottom = win.geometry().bottom()
        win.adjustSize()
        win.move(win.x(), bottom - win.height() + 1)

    def place():
        win.adjustSize()
        geo = app.primaryScreen().availableGeometry()
        win.move(QPoint(geo.right() - win.width() - 24, geo.bottom() - win.height() - 24))

    # Talking to TARS over the same token-protected bus the page uses.
    sock = QWebSocket()
    lines = {"you": "", "tars": ""}
    hide_timer = QTimer(singleShot=True, interval=8000)
    hide_timer.timeout.connect(lambda: (caption.hide(), fit()))

    def show_caption():
        def esc(t: str) -> str:
            return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        parts = []
        if lines["you"]:
            parts.append(f"<span style='color:#9aa6bf'>You: {esc(lines['you'])}</span>")
        if lines["tars"]:
            parts.append(f"<b>TARS:</b> {esc(lines['tars'][-400:])}")
        caption.setText("<br>".join(parts))
        caption.setVisible(bool(parts))
        hide_timer.stop()
        fit()

    def on_message(raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if msg.get("type") == "subtitle":
            who = msg.get("who")
            if who == "you":
                lines["you"], lines["tars"] = msg.get("text", ""), ""
            elif who == "tars":
                lines["tars"] = msg.get("text", "")
            show_caption()
        elif msg.get("type") == "state":
            state = msg.get("state", "")
            tray.setToolTip(f"TARS — {state}")
            if state == "idle" and caption.isVisible():
                hide_timer.start()  # fade out a while after it finishes talking

    sock.textMessageReceived.connect(on_message)
    sock.open(QUrl(args.ws))

    def send(msg: dict):
        sock.sendTextMessage(json.dumps(msg))

    def submit():
        text = entry.text().strip()
        if text:
            send({"type": "text", "text": text})
            entry.clear()

    entry.returnPressed.connect(submit)

    def type_message():
        win.show()
        win.raise_()
        win.activateWindow()
        entry.setFocus()

    def toggle_avatar():
        win.setVisible(not win.isVisible())

    def quit_tars():
        send({"type": "quit"})  # TARS stops; it also closes this window
        QTimer.singleShot(1500, app.quit)

    icon = QIcon(str(Path(__file__).with_name("icon.svg")))
    app.setWindowIcon(icon)
    menu = QMenu()
    menu.addActions(
        [
            QAction("Type a message", menu, triggered=type_message),
            QAction("Show / hide avatar", menu, triggered=toggle_avatar),
        ]
    )
    menu.addSeparator()
    menu.addAction(QAction("Quit TARS", menu, triggered=quit_tars))
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("TARS")
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: (
            toggle_avatar() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
    )
    tray.show()  # top bar (Ubuntu's AppIndicator extension)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    view.customContextMenuRequested.connect(lambda pos: menu.exec(view.mapToGlobal(pos)))

    if args.snapshot:
        times = [float(t) for t in args.snapshot_at.split(",")]
        for i, t in enumerate(times):
            QTimer.singleShot(
                int(t * 1000), lambda i=i: win.grab().save(f"{args.snapshot}-{i}.png")
            )
        QTimer.singleShot(int(times[-1] * 1000) + 500, app.quit)

    place()
    win.show()
    drag = DragFilter(win)
    # The page renders into a child widget that only exists after loading starts.
    view.loadFinished.connect(
        lambda _ok: view.focusProxy() and view.focusProxy().installEventFilter(drag)
    )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
