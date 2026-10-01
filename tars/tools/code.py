"""
Coding aids: check code with whatever linters exist (preferring the project's
own .venv), targeted edits that show the change and ask first (with a backup
for undo), and a syntax check that needs no tools at all.
"""

import ast
import difflib
import shlex
import shutil
import time
from pathlib import Path

from tars import TARS_HOME
from tars.agent.policy import check_read, check_write, resolve
from tars.agent.tools import Context, Registry, Tier, obj
from tars.tools.files import missing
from tars.tools.shell import run_command

BACKUPS = TARS_HOME / "backups"
_undo: list[tuple[Path, Path]] = []  # (original file, backup copy), newest last


def _project_bin(start: Path, tool: str) -> str | None:
    """Prefer <project>/.venv/bin/<tool> (or venv/), else the system one."""
    for d in [start, *start.parents]:
        for venv in (".venv", "venv"):
            cand = d / venv / "bin" / tool
            if cand.exists():
                return str(cand)
        if (d / ".git").exists() or (d / "pyproject.toml").exists():
            break
    return shutil.which(tool)


def _syntax(paths: list[Path]) -> list[str]:
    problems = []
    for p in paths:
        try:
            ast.parse(p.read_text(errors="replace"), filename=str(p))
        except SyntaxError as e:
            problems.append(f"{p.name}:{e.lineno}: syntax error: {e.msg}")
    return problems


async def check_code(ctx: Context, path: str) -> str:
    target = resolve(path, ctx.home)
    check_read(target, ctx.home)
    if not target.exists():
        return missing(target, ctx)
    base = target if target.is_dir() else target.parent
    files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
    files = [
        f for f in files if not any(part in (".venv", "venv", "node_modules") for part in f.parts)
    ][:200]
    report = [f"checked {len(files)} Python file(s) in {target.name}"]
    problems = _syntax(files)
    report.append("syntax: " + ("; ".join(problems) if problems else "ok"))
    for tool, args in (("ruff", ["check", "--output-format=concise"]), ("pylint", ["--score=n", "--output-format=parseable"]),
                       ("mypy", ["--no-error-summary"])):  # fmt: skip
        exe = _project_bin(base, tool)
        if not exe:
            continue
        cmd = shlex.join([exe, *args, str(target)])
        out = await run_command(ctx, cmd, timeout=120)
        lines = [ln for ln in out.splitlines()[1:] if ln.strip() and not ln.startswith("*****")]
        report.append(
            f"{tool}: "
            + ("no issues" if not lines else f"{len(lines)} line(s)\n" + "\n".join(lines[:25]))
        )
    if len(report) == 2:
        report.append(
            "(no linters found: install ruff or pylint in the project's .venv for more checks)"
        )
    return "\n".join(report)


async def edit_file(ctx: Context, path: str, find: str, replace: str) -> str:
    p = resolve(path, ctx.home)
    check_write(p, ctx.home)
    if not p.exists():
        return missing(p, ctx)
    if not p.is_file():
        return f"error: {path} is not a file"
    text = p.read_text()
    count = text.count(find)
    if count == 0:
        return "error: the text to replace was not found; read_file and copy it exactly"
    if count > 1:
        return (
            f"error: that text appears {count} times; include more surrounding lines so it's unique"
        )
    new = text.replace(find, replace, 1)
    diff = "".join(
        list(difflib.unified_diff(text.splitlines(True), new.splitlines(True), n=1))[2:]
    )[:1500]
    changed = sum(
        1 for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    )
    await ctx.require(Tier.T2, f"change {changed} lines in {p.name}")
    backup = BACKUPS / time.strftime("%Y%m%d-%H%M%S") / p.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, backup)
    p.write_text(new)
    _undo.append((p, backup))
    syntax = _syntax([p]) if p.suffix == ".py" else []
    return f"edited {p.name} (backup kept; undo_edit reverts)\n{diff}" + (
        f"\nwarning: {syntax[0]}" if syntax else ""
    )


async def undo_edit(ctx: Context) -> str:
    if not _undo:
        return "nothing to undo"
    original, backup = _undo[-1]
    await ctx.require(Tier.T2, f"undo the last edit to {original.name}")
    shutil.copy2(backup, original)
    _undo.pop()
    return f"restored {original.name} to before the last edit"


def register(reg: Registry):
    path = {
        "type": "string",
        "description": "file or folder; relative paths start in the home folder",
    }
    reg.tool("check_code", "Check Python code for errors: syntax, then ruff / pylint / mypy if available.",
             obj(["path"], path=path), speak="Checking the code")(check_code)  # fmt: skip
    reg.tool(
        "edit_file",
        "Change code in a file: replace one exact, unique snippet (copy it from read_file) with new text. "
        "Shows the change and asks first; keeps a backup.",
        obj(["path", "find", "replace"], path=path, find={"type": "string"}, replace={"type": "string"}),
        tier=Tier.T1,
    )(edit_file)  # fmt: skip
    reg.tool("undo_edit", "Revert the last edit_file change.", tier=Tier.T1)(undo_edit)
