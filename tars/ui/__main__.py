"""
The avatar window: a transparent, always-on-top Live2D overlay.

    .venv/bin/python -m tars.ui --ws ws://127.0.0.1:8765/?token=...

Normally started by `python -m tars.voice`. Runs under XWayland, because
GNOME's Wayland compositor doesn't let native apps stay on top or choose
their position. Drag it with the left mouse button; right-click for options.

The page is served through a private tars:// scheme instead of file:// (whose
URLs Chromium's fetch() refuses), so no network port is opened for it:
  tars://app/...     the built avatar app  (~/.local/share/tars/avatar/app)
  tars://avatar/...  Cubism Core + model    (~/.local/share/tars/avatar)
"""

import argparse
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # XWayland: always-on-top + positioning

from PyQt6.QtCore import QBuffer, QByteArray, QEvent, QObject, QPoint, Qt, QUrl
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMenu

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", required=True, help="avatar bus URL (with token)")
    ap.add_argument("--size", default="320x420", help="window WIDTHxHEIGHT")
    ap.add_argument("--zoom", type=float, default=2.2, help="1 = full body; larger = closer")
    ap.add_argument("--y", type=float, default=-1.1, help="vertical offset of the model")
    ap.add_argument("--snapshot", help="testing: save PNGs of the window to this prefix")
    ap.add_argument("--snapshot-at", default="6,9,12,15", help="seconds after start")
    args = ap.parse_args()
    if not (ROOTS["app"] / "index.html").exists():
        sys.exit("avatar app not built: run `.venv/bin/python -m tars.ui.live2d.build`")

    register_scheme()
    app = QApplication(sys.argv)
    app.setApplicationName("TARS")
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
    view.resize(w, h)
    geo = app.primaryScreen().availableGeometry()
    view.move(QPoint(geo.right() - w - 24, geo.bottom() - h - 24))
    view.load(
        QUrl(f"tars://app/index.html?ws={quote(args.ws, safe='')}&zoom={args.zoom}&y={args.y}")
    )

    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    menu = QMenu()
    menu.addActions(
        [
            QAction("Hide avatar", menu, triggered=view.hide),
            QAction("Quit avatar", menu, triggered=app.quit),
        ]
    )
    view.customContextMenuRequested.connect(lambda pos: menu.exec(view.mapToGlobal(pos)))

    if args.snapshot:
        from PyQt6.QtCore import QTimer

        times = [float(t) for t in args.snapshot_at.split(",")]
        for i, t in enumerate(times):
            QTimer.singleShot(
                int(t * 1000), lambda i=i: view.grab().save(f"{args.snapshot}-{i}.png")
            )
        QTimer.singleShot(int(times[-1] * 1000) + 500, app.quit)

    view.show()
    drag = DragFilter(view)
    # The page renders into a child widget that only exists after loading starts.
    view.loadFinished.connect(
        lambda _ok: view.focusProxy() and view.focusProxy().installEventFilter(drag)
    )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
