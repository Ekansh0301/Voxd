import pytest

from tars.voice.pttd import TRIGGERS, PttState, find_devices

RCTRL, SIDE, KEY_C, BTN_LEFT, BTN_TOUCH = 97, 0x113, 46, 0x110, 0x14A


def run(state, events):
    return [e for code, val in events if (e := state.feed(code, val))]


def test_hold_and_release_is_down_up():
    assert run(PttState({RCTRL}), [(RCTRL, 1), (RCTRL, 2), (RCTRL, 2), (RCTRL, 0)]) == [
        "down",
        "up",
    ]


def test_shortcut_while_holding_cancels_and_suppresses_up():
    s = PttState({RCTRL})
    assert run(s, [(RCTRL, 1), (KEY_C, 1), (KEY_C, 0), (RCTRL, 0)]) == ["down", "cancel"]


def test_other_keys_alone_do_nothing():
    assert run(PttState({RCTRL}), [(KEY_C, 1), (KEY_C, 0)]) == []


def test_ctrl_click_cancels_but_touchpad_contact_does_not():
    assert run(PttState({RCTRL}), [(RCTRL, 1), (BTN_LEFT, 1), (RCTRL, 0)]) == ["down", "cancel"]
    assert run(PttState({RCTRL}), [(RCTRL, 1), (BTN_TOUCH, 1), (RCTRL, 0)]) == ["down", "up"]


def test_second_trigger_while_holding_is_ignored():
    s = PttState({RCTRL, SIDE})
    assert run(s, [(SIDE, 1), (RCTRL, 1), (RCTRL, 0), (SIDE, 0)]) == ["down", "up"]


def test_state_resets_after_cancel():
    s = PttState({RCTRL})
    run(s, [(RCTRL, 1), (KEY_C, 1), (RCTRL, 0)])
    assert run(s, [(RCTRL, 1), (RCTRL, 0)]) == ["down", "up"]


def test_finds_keyboards_but_not_touchpads():
    devs = find_devices({TRIGGERS["KEY_RIGHTCTRL"]})
    if not devs:
        pytest.skip("no keyboards on this machine (e.g. CI)")
    assert all(p.startswith("/dev/input/event") for p in devs)
    assert not any("Touchpad" in name for name in devs.values())
