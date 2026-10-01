import asyncio

import pytest

from tars.agent.tools import Context, Denied
from tars.tools import files


@pytest.fixture
def ctx(tmp_path):
    async def yes(_summary):
        return True

    return Context(home=tmp_path, approve=yes, desktop=False)


def run(coro):
    return asyncio.run(coro) if asyncio.iscoroutine(coro) else coro


def test_move_into_new_folder_keeps_names(ctx, tmp_path):
    for i in range(3):
        (tmp_path / "Desktop").mkdir(exist_ok=True)
        (tmp_path / f"Desktop/s{i}.png").write_text(str(i))
    for i in range(3):
        run(files.move_path(ctx, f"Desktop/s{i}.png", "Pictures/screens"))
    assert sorted(p.name for p in (tmp_path / "Pictures/screens").iterdir()) == [
        "s0.png",
        "s1.png",
        "s2.png",
    ]


def test_rename_still_works(ctx, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    run(files.move_path(ctx, "a.txt", "b.txt"))
    assert (tmp_path / "b.txt").read_text() == "x"


def test_copy_is_exact(ctx, tmp_path):
    (tmp_path / "r.txt").write_bytes(b"line\n\x00binary")
    run(files.copy_path(ctx, "r.txt", "r.bak"))
    assert (tmp_path / "r.bak").read_bytes() == b"line\n\x00binary"


def test_overwrite_needs_approval(tmp_path):
    async def no(_summary):
        return False

    c = Context(home=tmp_path, approve=no, desktop=False)
    (tmp_path / "a.txt").write_text("keep")
    with pytest.raises(Denied):
        run(files.write_file(c, "a.txt", "new", overwrite=True))
    assert (tmp_path / "a.txt").read_text() == "keep"


def test_trash_is_reversible_and_never_home(ctx, tmp_path):
    (tmp_path / "old.log").write_text("x")
    run(files.trash_path(ctx, "old.log"))
    assert (tmp_path / ".trash-tars/old.log").exists()
    with pytest.raises(Denied):
        run(files.trash_path(ctx, "~"))


def test_secret_reads_refused(ctx, tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/id_ed25519").write_text("KEY")
    with pytest.raises(Denied):
        files.read_file(ctx, "~/.ssh/id_ed25519")


def test_timer_units_need_no_conversion():
    from tars.tools.system import _timers, set_timer

    async def go():
        a = await set_timer(Context(desktop=False), seconds=1, label="tea")
        b = await set_timer(Context(desktop=False), hours=1, minutes=30)
        for _, _, t in list(_timers.values()):
            t.cancel()
        return a, b

    a, b = asyncio.run(go())
    assert a.endswith("tea, 1s") and b.endswith("1h 30m")
