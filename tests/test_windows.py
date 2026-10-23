from tars.perception.windows import Window, find
from tars.tools.screen import _window_matches


def w(id, title, app, wm, focused=False):
    return Window(id, title, app, wm, 1, focused, False, 0, 0, 800, 600, 0)


WINS = [
    w(1, "Inbox - Outlook — Mozilla Firefox", "firefox_firefox.desktop", "firefox_firefox"),
    w(2, "Super Productivity", "superproductivity.desktop", "superProductivity"),
    w(3, "Spotube", "spotube.desktop", "spotube"),
    w(4, "notes.py - flash-copilot - Visual Studio Code", "code.desktop", "Code", focused=True),
    w(5, "~/Downloads", "com.mitchellh.ghostty.desktop", "com.mitchellh.ghostty"),
]


def test_find():
    assert find("super productivity", WINS).id == 2
    assert find("spotube", WINS).id == 3
    assert find("firefox", WINS).id == 1
    assert find("outlook", WINS).id == 1  # by title
    assert find("visual studio code", WINS).id == 4
    assert find("ghostty", WINS).id == 5
    assert find("calculator", WINS) is None


def _win(title, app, wm_class, focused=False):
    return Window(id=1, title=title, app=app, wm_class=wm_class, pid=1, focused=focused,
                  minimized=False, x=0, y=0, width=1, height=1, workspace=0)  # fmt: skip


def test_vs_code_found_by_its_everyday_name():
    code = _win("README.md - foresight - Visual Studio Code", "Visual Studio Code", "code")
    other = _win("LeetCode - Mozilla Firefox", "Firefox", "firefox_firefox", focused=True)
    for name in ("vs code", "VS Code", "vscode", "visual studio code"):
        assert find(name, [other, code]) is code
        assert _window_matches(name, "code", code.title)
    assert not _window_matches("vs code", "firefox", other.title)
