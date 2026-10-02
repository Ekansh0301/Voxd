import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.tools import research


def test_duckduckgo_redirect_unwrapped():
    href = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdownloads%2F&rut=abc"
    assert research._real_url(href) == "https://www.python.org/downloads/"
    assert research._real_url("https://example.com/a") == "https://example.com/a"


def test_blocked_sites_not_read():
    with pytest.raises(Denied):
        asyncio.run(research.read_page(Context(desktop=False), "https://courses.iiit.ac.in/my"))
