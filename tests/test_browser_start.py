import asyncio

import pytest

from tars.tools import browser


def test_normal_firefox_open_is_reported(monkeypatch):
    monkeypatch.setattr(browser, "_firefox_listening", lambda: False)
    monkeypatch.setattr(browser, "_normal_firefox_running", lambda: True)
    with pytest.raises(ConnectionError, match="open normally"):
        asyncio.run(browser.ensure_firefox())


def test_starts_firefox_tars_when_closed(monkeypatch):
    started = []
    state = {"up": False}

    def popen(argv, **kw):
        started.append(argv)
        state["up"] = True

    async def fast_sleep(_):
        return None

    monkeypatch.setattr(browser, "_firefox_listening", lambda: state["up"])
    monkeypatch.setattr(browser, "_normal_firefox_running", lambda: False)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser.asyncio, "sleep", fast_sleep)
    asyncio.run(browser.ensure_firefox())
    assert started and started[0][0].endswith("firefox-tars.sh")


def test_tab_for_picks_newest_matching_tab():
    pages = ">[0] Inbox (https://outlook.office365.com/mail/)\n [1] ChatGPT (https://chatgpt.com/)\n [2] New chat (https://chatgpt.com/c/1)"
    assert browser._tab_for(pages, "chatgpt.com") == 2
    assert browser._tab_for(pages, "outlook.office365.com") == 0
    assert browser._tab_for(pages, "github.com") is None
