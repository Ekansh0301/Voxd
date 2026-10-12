from pathlib import Path

from tars.agent.tools import Context
from tars.sites import SiteRegistry
from tars.tools.files import read_file


def _ctx(tmp_path: Path) -> Context:
    return Context(home=tmp_path, sites=SiteRegistry(), approve=None, desktop=False)


def test_a_single_line_comes_numbered_with_context(tmp_path):
    (tmp_path / "f.py").write_text("".join(f"line {i}\n" for i in range(1, 201)))
    out = read_file(_ctx(tmp_path), "f.py", start_line=34)
    assert out.startswith("f.py, lines 31-70 of 200:") or "lines 31-70 of 200" in out
    assert "  34| line 34" in out


def test_ranges_and_bounds(tmp_path):
    (tmp_path / "f.py").write_text("".join(f"x{i}\n" for i in range(1, 11)))
    assert read_file(_ctx(tmp_path), "f.py", start_line=2, end_line=3).endswith(
        "   2| x2\n   3| x3"
    )
    assert "only 10 lines" in read_file(_ctx(tmp_path), "f.py", start_line=50)


def test_long_files_say_what_was_shown(tmp_path):
    (tmp_path / "big.py").write_text(
        "".join(f"value_{i} = {i} * 2  # some comment\n" for i in range(500))
    )
    out = read_file(_ctx(tmp_path), "big.py")
    assert len(out) < 2500  # the loop keeps 2500 characters of a result
    assert "[500 lines; showing lines 1-" in out and "start_line" in out


def test_line_answers_without_reading_are_held_back(tmp_path, monkeypatch):
    import asyncio

    from tars.agent import loop
    from tars.agent.tools import Registry

    (tmp_path / "f.py").write_text("".join(f"x{i}\n" for i in range(1, 80)))
    replies = [
        [("text", "Line 60 writes the JSON.")],  # made up: no read yet
        [
            (
                "tool_calls",
                [
                    {
                        "id": "1",
                        "name": "read_file",
                        "arguments": {"path": "f.py", "start_line": 60, "end_line": 60},
                    }
                ],
            )
        ],  # fmt: skip
        [("text", "Line 60 is x60.")],
    ]

    async def fake_stream(*_a, **_k):
        for item in replies.pop(0):
            yield item

    monkeypatch.setattr(loop, "stream_turn", fake_stream)
    reg = Registry()
    reg.tool("read_file", "", {"type": "object", "properties": {}})(read_file)
    spoken: list[str] = []
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "And line 60?"}]
    result = asyncio.run(loop.run_turn(msgs, reg, _ctx(tmp_path), "e", "m", on_text=spoken.append))
    assert result.answer == "Line 60 is x60." and [s["tool"] for s in result.steps] == ["read_file"]
    assert "writes the JSON" not in "".join(spoken)  # the guess was never spoken
