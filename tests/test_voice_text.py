"""What TARS speaks, shows and keeps in its history."""

from tars.voice.service import _note, _plain


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
