"""
Your apps (config/apps.yaml): open by name or alias with the right launch
flags, open files in the right app, VS Code at a line, a Ghostty terminal in a
folder (optionally running a command inside tmux), and Super Productivity
reminders through its Local REST API.
"""

import difflib
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml  # type: ignore[import-untyped]

from tars.agent.policy import check_read, classify_command, resolve
from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.config import USER
from tars.timeparse import parse_when
from tars.tools.files import missing

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO / "config" / "apps.yaml"
SECRETS = USER.parent / "secrets.yaml"  # e.g. superproductivity_token: ... (written by you)
SP_API = "http://127.0.0.1:3876"


@dataclass
class App:
    key: str
    launch: list[str]
    aliases: list[str] = field(default_factory=list)
    purpose: str = ""
    access: str = "full"
    handles: list[str] = field(default_factory=list)
    notes: str = ""


class AppRegistry:
    def __init__(self, path: Path = CONFIG):
        data = yaml.safe_load(path.read_text())["apps"]
        self.apps = {
            k: App(key=k, **{**v, "launch": [a.replace("{repo}", str(REPO)) for a in v["launch"]]})
            for k, v in data.items()
        }

    def resolve(self, name: str) -> App | None:
        q = name.lower().strip()
        names = {a.lower(): app for app in self.apps.values() for a in [app.key, *app.aliases]}
        if q in names:
            return names[q]
        close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.8)
        return names[close[0]] if close else None

    def for_file(self, path: Path) -> App | None:
        return next((a for a in self.apps.values() if path.suffix.lower() in a.handles), None)

    def summary(self) -> str:
        return "; ".join(f"{a.key}: {a.purpose}" for a in self.apps.values())


def _spawn(ctx: Context, argv: list[str], what: str) -> None:
    ctx.actions.append(what)
    if ctx.desktop:
        subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )


def launch(ctx: Context, app: App, extra: list[str] | None = None) -> str:
    if app.access == "blocked":
        raise Denied(f"{app.key} is blocked for TARS")
    _spawn(ctx, app.launch + (extra or []), f"launch {app.key} {' '.join(extra or [])}".strip())
    return f"opened {app.key}"


def register(reg: Registry, apps: AppRegistry):
    def open_file(ctx: Context, path: str, app: str = "") -> str:
        p = resolve(path, ctx.home)
        check_read(p, ctx.home)
        if not p.exists():
            return missing(p, ctx)
        target = apps.resolve(app) if app else apps.for_file(p)
        if app and target is None:
            return f"error: unknown app {app!r}"
        if target is not None:
            return launch(ctx, target, [str(p)]) + f" with {p.name}"
        _spawn(ctx, ["gio", "open", str(p)], f"open {p}")
        return f"opened {p.name} with its default app"

    def vscode_open(ctx: Context, path: str, line: int | None = None) -> str:
        p = resolve(path, ctx.home)
        check_read(p, ctx.home)
        if not p.exists():
            return missing(p, ctx)
        code = apps.apps["vscode"]
        extra = ["-g", f"{p}:{line}"] if line and p.is_file() else [str(p)]
        launch(ctx, code, extra)
        return f"opened {p.name} in VS Code" + (f" at line {line}" if line else "")

    async def terminal_open(ctx: Context, folder: str = "~", command: str = "") -> str:
        d = resolve(folder, ctx.home)
        if not d.is_dir():
            return f"error: {folder} is not a folder"
        argv = ["ghostty", f"--working-directory={d}"]
        if command:
            tier, reason = classify_command(command, ctx.home)  # same rules as run_command
            if tier >= Tier.T2:
                await ctx.require(tier, f"run `{command}` in a terminal ({reason})")
            # inside tmux, so TARS can read the output afterwards (read_terminal)
            argv += ["-e", "tmux", "new-session", "-c", str(d), f"{command}; exec $SHELL"]
        _spawn(ctx, argv, f"terminal {d} {command}".strip())
        return f"opened a terminal in {d}" + (f" running {command}" if command else "")

    async def add_reminder(ctx: Context, title: str, when: str = "", notes: str = "") -> str:
        at = parse_when(when) if when else None
        if when and at is None:
            return f"error: couldn't understand the time {when!r}; say e.g. 'tomorrow at 9 am' or 'in 30 minutes'"
        token = (
            (yaml.safe_load(SECRETS.read_text()) or {}).get("superproductivity_token")
            if SECRETS.exists()
            else None
        )
        ctx.actions.append(f"reminder {title!r} {at.isoformat() if at else ''}")
        if not ctx.desktop:
            return (
                f"added task {title!r}"
                + (f" with a reminder at {at:%a %d %b %H:%M}" if at else "")
                + " (dry run)"
            )
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{SP_API}/tasks", headers=headers, json={"title": title, "notes": notes}
                )
                if r.status_code >= 400:
                    return f"error: Super Productivity API said {r.status_code}: {r.text[:200]}"
                task = r.json()
                task_id = task.get("id") or task.get("data", {}).get("id")
                if at and task_id:
                    ms = int(at.timestamp() * 1000)
                    r = await client.patch(f"{SP_API}/tasks/{task_id}", headers=headers,
                                           json={"deadlineWithTime": ms, "deadlineRemindAt": ms})  # fmt: skip
                    if r.status_code >= 400:
                        return f"added {title!r} but the reminder failed: {r.status_code} {r.text[:150]}"
            return f"added task {title!r} in Super Productivity" + (
                f" with a reminder at {at:%a %d %b, %I:%M %p}" if at else ""
            )
        # No API token: the URL scheme can create the task, but not set a reminder.
        url = "superproductivity://create-task?" + urllib.parse.urlencode(
            {"title": title, "notes": notes}
        )
        _spawn(ctx, ["xdg-open", url], f"open {url}")
        extra = (" I couldn't set the reminder time: enable Super Productivity's local REST API "
                 "and save its token in ~/.config/tars/secrets.yaml.") if at else ""  # fmt: skip
        return f"added task {title!r} to Super Productivity.{extra}"

    def list_apps(ctx: Context) -> str:
        return apps.summary()

    path = {"type": "string", "description": "path; relative paths start in the home folder"}
    reg.tool("open_file", "Open a file in the right app (PDFs in Okular) or in a named app.",
             obj(["path"], path=path, app={"type": "string"}), tier=Tier.T1, speak="Opening")(open_file)  # fmt: skip
    reg.tool("vscode_open", "Open a folder or file in VS Code, optionally at a line.",
             obj(["path"], path=path, line={"type": "integer"}), tier=Tier.T1, speak="Opening VS Code")(vscode_open)  # fmt: skip
    reg.tool("terminal_open", "Open a Ghostty terminal in a folder, optionally running a command.",
             obj([], folder=path, command={"type": "string"}), tier=Tier.T1)(terminal_open)  # fmt: skip
    reg.tool("add_reminder", "Add a task to Super Productivity, optionally with a reminder time "
             "in the user's words ('tomorrow at 9 am', 'in 30 minutes').",
             obj(["title"], title={"type": "string"}, when={"type": "string"}, notes={"type": "string"}),
             tier=Tier.T1)(add_reminder)  # fmt: skip
    reg.tool("list_apps", "The user's apps and what each is for.")(list_apps)
