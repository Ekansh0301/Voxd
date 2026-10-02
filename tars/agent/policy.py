"""
What the agent may run and touch, decided in code (never by the model).

Shell: refused outright / read-only (T0, sandboxed) / needs approval (T2).
Paths: secrets are never readable; writes stay inside the home folder.
"""

import fnmatch
import re
import shlex
from pathlib import Path

from tars.agent.tools import Denied, Tier

# Read-only programs that are safe to run without asking (inside the sandbox).
READ_ONLY = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "find", "stat", "du",
    "df", "free", "uptime", "date", "whoami", "id", "hostname", "uname", "which", "type",
    "file", "nproc", "lscpu", "lsblk", "lsusb", "lspci", "nvidia-smi", "ps", "pwd", "echo",
    "tree", "sort", "uniq", "cut", "tr", "awk", "basename", "dirname", "realpath", "env",
    "printenv", "locale", "sensors", "upower", "ip", "ss", "journalctl", "systemctl", "git",
    "python3", "python", "node", "pip", "pip3", "dpkg", "apt", "ollama", "md5sum", "sha256sum",
    "column", "less", "more", "jq", "cal", "diff", "cmp", "seq",
    # code checkers (read-only unless told to fix; see _read_only)
    "pylint", "flake8", "mypy", "pyright", "ruff", "black", "eslint", "shellcheck", "pyflakes",
    "pycodestyle",
}  # fmt: skip
# `python -m <module>` that only reads code
PY_MODULES_READ_ONLY = {
    "pylint",
    "mypy",
    "flake8",
    "pyflakes",
    "pycodestyle",
    "py_compile",
    "ruff",
    "black",
}
# Read-only only with these first arguments (or flags).
SUBCOMMANDS = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "describe", "tag", "blame", "--version", "version"},
    "systemctl": {"status", "is-active", "is-enabled", "list-units", "list-timers", "--user"},
    "pip": {"list", "show", "freeze", "--version"},
    "pip3": {"list", "show", "freeze", "--version"},
    "apt": {"list", "show", "search", "policy"},
    "dpkg": {"-l", "-L", "-s", "--list", "--status"},
    "ollama": {"list", "ps", "show"},
    "python3": {"--version", "-V"},
    "python": {"--version", "-V"},
    "node": {"--version", "-v"},
    "ip": {"addr", "a", "link", "route", "r", "-br", "-c"},
}  # fmt: skip
FORBIDDEN_FLAGS = {"find": {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint"}}
NEVER = {"sudo", "su", "doas", "pkexec", "mkfs", "fdisk", "parted", "wipefs", "shred", "chroot"}
NEVER_PATTERNS = [
    r"\brm\s+(-\w*\s+)*(/|~|\$HOME)(\s|$)",  # rm -rf / or ~
    r"\bdd\b.*\bof=/dev/",
    r">\s*/dev/(sd|nvme|mmcblk)",
    r"(curl|wget)[^|]*\|\s*(ba|z)?sh\b",  # pipe-to-shell
    r":\(\)\s*\{.*\};\s*:",  # fork bomb
    r"\bchmod\s+(-\w+\s+)*[0-7]*777\s+/",
]
SHELL_CONTROL = re.compile(r"[;&`]|\$\(|\|\||>|<|\n")

SECRETS = [
    ".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".mozilla", ".aws",
    ".kube", ".docker/config.json", ".netrc", ".git-credentials", ".config/google-chrome",
    ".config/chromium", ".config/BraveSoftware", ".config/gh/hosts.yml", ".pki",
]  # fmt: skip
SECRET_NAMES = ["id_rsa*", "id_ed25519*", "*.pem", "*.key", ".env", ".env.*", "*.kdbx"]


DELETERS = {"rm", "rmdir", "unlink", "shred", "srm", "wipe"}
TRASH_HINT = (
    "TARS doesn't delete permanently: use trash_path (moves it to the Trash, so it can be undone)"
)


def _command_words(cmd: str) -> list[list[str]]:
    """argv of each command in a pipeline / list (a | b; c && d), env assignments dropped."""
    out = []
    for seg in re.split(r"\|\||&&|[|;&\n]", cmd):
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        while words and (
            "=" in words[0].split("/")[0] or words[0] in ("env", "nohup", "nice", "time", "command")
        ):
            words = words[1:]
        if words:
            out.append(words)
    return out


def classify_command(cmd: str, home: Path) -> tuple[Tier, str]:
    """Returns (tier, reason). Raises Denied for commands that are never allowed."""
    if not cmd.strip():
        raise Denied("empty command")
    for pat in NEVER_PATTERNS:
        if re.search(pat, cmd):
            raise Denied("destructive pattern")
    if mentions_secret(cmd, home):
        raise Denied("touches a secret file or folder")
    try:
        words = shlex.split(cmd)
    except ValueError as e:
        raise Denied(f"unparseable command: {e}") from e
    if any(w in NEVER for w in words) or any(Path(w).name in NEVER for w in words):
        raise Denied("needs root or is a disk tool; run it yourself")
    for argv in _command_words(cmd):
        prog = Path(argv[0]).name
        if (
            prog in DELETERS
            or (prog == "find" and "-delete" in argv)
            or (
                prog == "git"
                and "clean" in argv
                and any(a.startswith("-") and "f" in a for a in argv)
            )
        ):
            raise Denied(TRASH_HINT)
    # Pipelines of read-only commands stay read-only; anything else needs approval.
    if SHELL_CONTROL.search(cmd):
        return Tier.T2, "uses shell control operators or redirection"
    for part in (shlex.split(p) for p in cmd.split("|")):
        if not part or not _read_only(part):
            return Tier.T2, f"{part[0] if part else 'empty'} may change things"
    return Tier.T0, "read-only"


def _read_only(argv: list[str]) -> bool:
    prog = Path(argv[0]).name
    if prog not in READ_ONLY:
        return False
    if prog in ("python", "python3") and len(argv) >= 3 and argv[1] == "-m":
        module = argv[2]
        if module in ("ruff", "black"):  # read-only only with check/diff flags
            return _read_only([module, *argv[3:]])
        return module in PY_MODULES_READ_ONLY
    if prog in SUBCOMMANDS and (len(argv) < 2 or argv[1] not in SUBCOMMANDS[prog]):
        return False  # e.g. `git push`, `pip install`, bare `python3` (runs code)
    fixes = {"--fix", "--unsafe-fixes", "--fix-only", "-w", "--write"}
    if prog == "ruff":
        sub = argv[1] if len(argv) > 1 else ""
        return (sub == "check" and not fixes & set(argv)) or (
            sub == "format" and bool({"--check", "--diff"} & set(argv))
        )
    if prog == "black":
        return bool({"--check", "--diff"} & set(argv))
    if prog == "eslint" and fixes & set(argv):
        return False
    if prog in FORBIDDEN_FLAGS and FORBIDDEN_FLAGS[prog] & set(argv[1:]):
        return False
    if prog == "awk" and any("system" in a or "print >" in a for a in argv[1:]):
        return False
    return True


def mentions_secret(text: str, home: Path) -> bool:
    expanded = text.replace("~", str(home)).replace("$HOME", str(home))
    for s in SECRETS:
        if f"/{s}" in expanded or expanded.startswith(s) or f" {s}" in expanded:
            return True
    return any(fnmatch.fnmatch(Path(w).name, pat) for w in expanded.split() for pat in SECRET_NAMES)


def resolve(path: str, home: Path) -> Path:
    """User/model path -> absolute path (relative paths are relative to home)."""
    p = Path(path.replace("$HOME", str(home))).expanduser()
    if str(p).startswith("~"):
        p = home / str(p)[2:]
    if not p.is_absolute():
        p = home / p
    # expanduser() uses the real home; map it onto ctx.home (differs in evals)
    real = Path.home()
    if home != real and p.is_relative_to(real):
        p = home / p.relative_to(real)
    return Path(*_normalise(p.parts))


def _normalise(parts: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for part in parts:
        if part == "..":
            if len(out) > 1:
                out.pop()
        elif part != ".":
            out.append(part)
    return out


def check_read(path: Path, home: Path) -> None:
    if _is_secret(path, home):
        raise Denied(f"{path} holds secrets")


def check_write(path: Path, home: Path) -> None:
    check_read(path, home)
    if not path.resolve().is_relative_to(home.resolve()):
        raise Denied(f"{path} is outside your home folder")
    rel = path.resolve().relative_to(home.resolve())
    if rel.parts and rel.parts[0] in (
        ".config",
        ".local",
        ".cache",
        ".bashrc",
        ".profile",
        ".zshrc",
    ):
        raise Denied(f"{path} is configuration; edit it yourself")


def _is_secret(path: Path, home: Path) -> bool:
    p = path.resolve() if path.exists() else path
    try:
        rel = p.relative_to(home.resolve() if home.exists() else home)
    except ValueError:
        rel = None
    if rel is not None:
        r = rel.as_posix()
        if any(r == s or r.startswith(s + "/") for s in SECRETS):
            return True
    return any(fnmatch.fnmatch(p.name, pat) for pat in SECRET_NAMES)
