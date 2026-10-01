import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.perception.keyboard import SPECIAL, InputError, keysym, parse_combo
from tars.tools.keys import press_keys, type_text


def test_keysyms():
    assert keysym("a") == ord("a") and keysym("*") == ord("*") and keysym("\n") == SPECIAL["enter"]
    assert keysym("₹") == 0x01000000 + ord("₹")
    assert parse_combo("ctrl+s") == [SPECIAL["ctrl"], ord("s")]
    assert parse_combo("Ctrl + Shift + T") == [SPECIAL["ctrl"], SPECIAL["shift"], ord("t")]
    assert parse_combo("Enter") == [SPECIAL["enter"]]
    with pytest.raises(InputError):
        parse_combo("ctrl+banana")


def test_sending_and_closing_keys_need_approval():
    asked: list[str] = []

    async def no(summary):
        asked.append(summary)
        return False

    ctx = Context(approve=no, desktop=False)
    with pytest.raises(Denied):
        asyncio.run(type_text(ctx, "hello", then_key="ctrl+enter"))
    with pytest.raises(Denied):
        asyncio.run(press_keys(ctx, "ctrl+s, alt+F4"))
    assert len(asked) == 2 and "send" in asked[0] and "closes" in asked[1]
    assert ctx.actions == []  # nothing recorded as done


def test_plain_keys_dry_run():
    ctx = Context(desktop=False)
    assert asyncio.run(press_keys(ctx, "ctrl+s")) == "pressed ctrl+s (dry run)"
    assert asyncio.run(type_text(ctx, "12*7", then_key="Enter")).startswith("typed 4")
    assert ctx.actions == ["keys ctrl+s", "type 4 chars + Enter"]
