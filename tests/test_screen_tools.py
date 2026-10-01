import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.perception.atspi import Atspi, Node
from tars.tools import screen

ACTION = ["org.a11y.atspi.Accessible", "org.a11y.atspi.Action"]


def node(role, name, ifaces=ACTION, children=(), showing=True, depth=1):
    n = Node(
        ("bus", f"/{name}"), role, name, {25, 8} if showing else set(), list(ifaces), depth=depth
    )
    n.children = list(children)
    for c in n.children:
        c.depth = depth + 1
    return n


def test_render_names_are_unique_and_skip_echo_labels():
    win = node("frame", "App", children=[
        node("push button", "OK", children=[node("label", "OK", ifaces=[])]),
        node("push button", "OK"),
        node("push button", "Send"),
        node("push button", "hidden", showing=False),
    ], depth=0)  # fmt: skip
    a = Atspi()
    text = a.render(win)
    assert "push button 'OK'" in text and "push button 'OK (2)'" in text
    assert "label 'OK'" not in text and "hidden" not in text
    assert set(a.labels) == {"OK", "OK (2)", "Send"}


def test_lookup_by_name_then_fuzzy(monkeypatch):
    nodes = {1: node("push button", "Compose"), 2: node("label", "Inbox", ifaces=[])}
    monkeypatch.setattr(screen, "_last", nodes)
    monkeypatch.setattr(screen, "_labels", {"Compose": 1, "Inbox": 2})
    assert screen._node(name="Compose")[0] == 1
    assert screen._node(name="compose")[0] == 1  # case-insensitive
    assert screen._node(name="Comp")[0] == 1  # contains
    with pytest.raises(ValueError):
        screen._node(name="Archive")


def test_risky_click_needs_approval_and_passwords_refused(monkeypatch):
    send, pw = node("push button", "Send"), node("password text", "Password")
    monkeypatch.setattr(screen, "_last", {1: send, 2: pw})
    monkeypatch.setattr(screen, "_labels", {"Send": 1, "Password": 2})
    ctx = Context(approve=None, desktop=False)  # nobody approves
    with pytest.raises(Denied):
        asyncio.run(screen.click(ctx, name="Send"))
    with pytest.raises(Denied):
        asyncio.run(screen.type_into(ctx, "hunter2", name="Password"))


def test_crop_regions(tmp_path):
    from PIL import Image

    from tars.tools.vision import crop_png

    p = tmp_path / "s.png"
    Image.new("RGB", (1920, 1080), "white").save(p)
    import io

    full = Image.open(io.BytesIO(crop_png(p, "full")))
    corner = Image.open(io.BytesIO(crop_png(p, "top-right")))
    assert full.size == (1280, 720) and corner.size == (960, 540)
