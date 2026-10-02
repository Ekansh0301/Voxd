import asyncio
import shutil
import subprocess

import pytest

from tars.agent.tools import Context, Denied
from tars.tools import code


def run(c):
    return asyncio.run(c)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(code, "BACKUPS", tmp_path / ".backups")
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj/app.py").write_text("def add(a, b):\n    return a - b\n\nprint(add(2, 3))\n")
    (tmp_path / "proj/broken.py").write_text("def f(:\n    pass\n")
    return tmp_path


def test_edit_shows_change_needs_approval_and_undoes(proj):
    async def yes(_):
        return True

    ctx = Context(home=proj, approve=yes, desktop=False)
    out = run(code.edit_file(ctx, "proj/app.py", "return a - b", "return a + b"))
    assert "-    return a - b" in out and "+    return a + b" in out
    assert "a + b" in (proj / "proj/app.py").read_text()
    run(code.undo_edit(ctx))
    assert "a - b" in (proj / "proj/app.py").read_text()


def test_edit_refused_or_ambiguous(proj):
    ctx = Context(home=proj, approve=None, desktop=False)
    with pytest.raises(Denied):
        run(code.edit_file(ctx, "proj/app.py", "return a - b", "return a + b"))
    assert "a - b" in (proj / "proj/app.py").read_text()
    assert "not found" in run(code.edit_file(ctx, "proj/app.py", "nope", "x"))


def _sandbox_ok() -> bool:
    return (
        bool(shutil.which("bwrap"))
        and subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--unshare-pid", "true"],
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _sandbox_ok(), reason="needs bubblewrap")
def test_check_code_reports_syntax_error(proj):
    out = run(code.check_code(Context(home=proj, desktop=False), "proj"))
    assert "broken.py:1: syntax error" in out


def test_missing_path_suggests_where_it_is(proj):
    (proj / ".ssh").mkdir()
    (proj / ".ssh/app.py").write_text("secret")
    out = run(code.check_code(Context(home=proj, desktop=False), "app.py"))
    assert "Did you mean ~/proj/app.py?" in out and ".ssh" not in out


PATCH = """--- a/proj/app.py
+++ b/proj/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
--- /dev/null
+++ b/proj/util.py
@@ -0,0 +1 @@
+TWO = 2
"""


def test_apply_patch_across_files_and_undo(proj):
    async def yes(_):
        return True

    ctx = Context(home=proj, approve=yes, desktop=False)
    out = run(code.apply_patch(ctx, PATCH))
    assert out.startswith("patched 2 file(s)") and "+2 -1" in out
    assert "a + b" in (proj / "proj/app.py").read_text() and (proj / "proj/util.py").exists()
    run(code.undo_edit(ctx))
    assert "a - b" in (proj / "proj/app.py").read_text()
    assert (
        not (proj / "proj/util.py").exists() and (proj / ".trash-tars/util.py").exists()
    )  # trashed, not deleted


def test_apply_patch_checks_first(proj):
    ctx = Context(home=proj, approve=None, desktop=False)
    bad = PATCH.replace("-    return a - b", "-    return a * b")
    assert "doesn't apply" in run(code.apply_patch(ctx, bad))
    with pytest.raises(Denied):  # applies, but nobody approved it
        run(code.apply_patch(ctx, PATCH))
    assert "a - b" in (proj / "proj/app.py").read_text()
