import asyncio
import shutil
import subprocess

import pytest

from tars.agent.tools import Context, Denied
from tars.tools.shell import run_command


def _sandbox_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    probe = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--unshare-pid", "true"]
    return subprocess.run(probe, capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not _sandbox_works(), reason="bubblewrap sandboxes unavailable here"
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def home(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_ed25519").write_text("SECRET")
    return tmp_path


def test_read_only_command_runs_in_home(home):
    out = run(run_command(Context(home=home, desktop=False), "cat notes.txt"))
    assert out.startswith("exit code 0") and "hello" in out


def test_read_only_sandbox_cannot_write_or_reach_network(home):
    async def yes(_):
        return True

    # writing is T2: refused without approval, allowed (home writable) with it
    with pytest.raises(Denied):
        run(run_command(Context(home=home, approve=None, desktop=False), "touch new.txt"))
    assert not (home / "new.txt").exists()
    run(run_command(Context(home=home, approve=yes, desktop=False), "touch new.txt"))
    assert (home / "new.txt").exists()  # approved -> writable home


def test_secrets_are_hidden_even_if_policy_missed_them(home):
    from tars.tools.shell import sandbox_argv

    argv = sandbox_argv("ls -a .ssh", home, writable=False)
    assert "--tmpfs" in argv and str(home / ".ssh") in argv
