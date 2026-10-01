from tars.perception.windows import Window, find


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
