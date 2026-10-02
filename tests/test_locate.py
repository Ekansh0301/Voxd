import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.tools.locate import _box, click_on_screen


def test_box_formats():
    assert _box('```json\n[{"bbox_2d": [30, 123, 62, 149], "label": "Search"}]\n```') == (
        30,
        123,
        62,
        149,
    )
    assert _box("[526, 938, 549, 976]") == (526, 938, 549, 976)
    assert _box("I can't see it") is None


def test_risky_targets_need_approval():
    with pytest.raises(Denied):
        asyncio.run(click_on_screen(Context(desktop=False), "the Send button"))
    assert asyncio.run(click_on_screen(Context(desktop=False), "Search")).endswith("(dry run)")
