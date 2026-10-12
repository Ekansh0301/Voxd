from tars.perception.windows import Window, find
from tars.tools.screen import _window_matches
from tars.voice.service import _note, _plain


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


def test_copied_action_notes_never_spoken():
    # the model once wrote a note instead of calling the tool (no timer was set)
    assert _plain("Setting a timer for 10 minutes.\n[done: set_timer(minutes=10)]") == (
        "Setting a timer for 10 minutes."
    )
    assert _plain("[done: set_timer(minutes=10)]").strip() == ""
    assert _plain("Done. (actions taken for this request: set_timer(minutes=10))") == "Done."


def test_note_goes_on_the_user_side():
    assert _note([]) == ""
    assert _note([("set_volume", {"level": 50})]) == (
        "\n(actions taken for this request: set_volume(level='50'))"
    )
