import asyncio
import types

import pytest

from tars.agent.tools import Context
from tars.perception import keyboard, windows
from tars.tools import browser


@pytest.fixture
def fake_desktop(monkeypatch):
    state = {"running": True, "keys": [], "started": False}

    class Kb:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def combo(self, keys):
            state["keys"].append(keys)
            if state.get("closes", True):
                state["running"] = False

    async def no_sleep(_s):
        pass

    async def started(url=""):
        state["started"] = True
        return True

    async def wins():
        return [types.SimpleNamespace(wm_class="firefox_firefox", app="Firefox")]

    async def activate(_w):
        return True

    monkeypatch.setattr(browser, "_firefox_listening", lambda: False)
    monkeypatch.setattr(browser, "_normal_firefox_running", lambda: state["running"])
    monkeypatch.setattr(browser, "ensure_firefox", started)
    monkeypatch.setattr(browser.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(keyboard, "Keyboard", Kb)
    monkeypatch.setattr(windows, "list_windows", wins)
    monkeypatch.setattr(windows, "activate", activate)
    return state


def _ctx(answer: bool) -> Context:
    async def approve(_s):
        return answer

    return Context(desktop=True, approve=approve)


def test_nothing_happens_without_a_yes(fake_desktop):
    out = asyncio.run(browser.restart_firefox(_ctx(False)))
    assert out.startswith("refused") and not fake_desktop["keys"] and not fake_desktop["started"]


def test_quits_normally_then_starts_firefox_tars(fake_desktop):
    out = asyncio.run(browser.restart_firefox(_ctx(True)))
    assert fake_desktop["keys"] == ["ctrl+q"] and fake_desktop["started"]
    assert out.startswith("restarted") and "tabs" in out


def test_a_question_from_firefox_is_left_to_the_user(fake_desktop):
    fake_desktop["closes"] = False  # e.g. "leave this page?"
    out = asyncio.run(browser.restart_firefox(_ctx(True)))
    assert out.startswith("error") and "question" in out and not fake_desktop["started"]
