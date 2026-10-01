"""
Your apps (config/apps.yaml): open by name or alias with the right launch
flags, open files in the right app, VS Code at a line, a Ghostty terminal in a
folder (optionally running a command inside tmux), and Super Productivity
reminders through its Local REST API.
"""

import asyncio
import difflib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import yaml  # type: ignore[import-untyped]

from tars.agent.policy import check_read, classify_command, resolve
from tars.agent.tools import Context, Denied, Registry, Tier, obj
from tars.perception.atspi import Atspi, Node
from tars.timeparse import parse_when
from tars.tools.files import missing

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO / "config" / "apps.yaml"
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


async def _sp_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            return (await client.get(f"{SP_API}/status")).status_code == 200
    except httpx.HTTPError:
        return False


def schedule_alarm(at: datetime, title: str) -> bool:
    """A transient systemd user timer that pops a notification at `at`. It outlives
    TARS (not a reboot) and shows in `systemctl --user list-timers` as tars-reminder-*."""
    unit = f"tars-reminder-{int(at.timestamp())}-{abs(hash(title)) % 10000}"
    r = subprocess.run(
        ["systemd-run", "--user", "--collect", f"--unit={unit}", f"--description=TARS reminder: {title}",
         f"--on-calendar={at.astimezone():%Y-%m-%d %H:%M:%S}", "--timer-property=AccuracySec=1s",
         "notify-send", "--urgency=critical", "--app-name=TARS", "--icon=alarm-symbolic", "Reminder", title],
        capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    return r.returncode == 0


def _walk(n: Node):
    yield n
    for c in n.children:
        yield from _walk(c)


async def _termius_hosts(a: Atspi) -> dict[str, Node]:
    """Host cards in Termius's Hosts list: {'ada': <button 'Ada ssh, user'>}."""
    hosts: dict[str, Node] = {}
    for app, w in await a.windows():
        if "termius" in app.lower() and w.name == "Termius":
            for n in _walk(await a.tree(w, max_nodes=1500, max_depth=40)):
                if n.role == "button" and " ssh" in n.name:
                    hosts[n.name.split(" ssh")[0].strip().lower()] = n
    return hosts


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
        ctx.actions.append(f"reminder {title!r} {at.isoformat() if at else ''}")
        spoken = f" at {at:%a %d %b, %I:%M %p}" if at else ""
        if not ctx.desktop:
            return f"added task {title!r}{spoken} (dry run)"
        if not await _sp_up():
            launch(ctx, apps.apps["superproductivity"])
            for _ in range(30):
                await asyncio.sleep(1)
                if await _sp_up():
                    break
            else:
                return "error: Super Productivity didn't start, or its local REST API is off (Settings → Misc)"
        task = {
            "title": title,
            "notes": notes,
            **({"dueWithTime": int(at.timestamp() * 1000)} if at else {}),
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{SP_API}/tasks", json=task)
        if r.status_code >= 400 or not r.json().get("ok"):
            return f"error: Super Productivity said {r.status_code}: {r.text[:200]}"
        if at is None:
            return f"added task {title!r} in Super Productivity"
        # The API can't set Super Productivity's own alarm (remindAt), so TARS sets one.
        if not schedule_alarm(at, title):
            return f"added {title!r}{spoken} in Super Productivity, but couldn't set the alarm"
        return f"added {title!r} in Super Productivity{spoken}, with a desktop alarm then"

    async def _sp_ready(ctx: Context) -> bool:
        if await _sp_up():
            return True
        launch(ctx, apps.apps["superproductivity"])
        for _ in range(30):
            await asyncio.sleep(1)
            if await _sp_up():
                return True
        return False

    async def list_tasks(ctx: Context) -> str:
        if not ctx.desktop:
            return "overdue: Return book (due Wed 01 Oct, 10:00 AM)\ntoday: Hisaab\n3 more tasks without a date (dry run)"
        if not await _sp_ready(ctx):
            return "error: Super Productivity didn't start, or its local REST API is off (Settings → Misc)"
        async with httpx.AsyncClient(timeout=10) as client:
            ids = [
                t["id"]
                for t in (await client.get(f"{SP_API}/tasks")).json()["data"]
                if not t.get("isDone")
            ]
            # the list leaves out dates; each task's own record has them
            tasks = [(await client.get(f"{SP_API}/tasks/{i}")).json()["data"] for i in ids]
        now = datetime.now().astimezone()
        today = now.date().isoformat()
        overdue: list[tuple[str, str]] = []
        due_today: list[tuple[str, str]] = []
        upcoming: list[tuple[str, str]] = []
        undated = 0
        for t in tasks:
            title = t.get("title", "?")
            if t.get("dueWithTime"):
                at = datetime.fromtimestamp(t["dueWithTime"] / 1000).astimezone()
                item = (at.isoformat(), f"{title} ({at:%a %d %b, %I:%M %p})")
                (
                    overdue if at < now else due_today if at.date() == now.date() else upcoming
                ).append(item)
            elif t.get("dueDay"):
                day = t["dueDay"]
                item = (day, f"{title} ({datetime.fromisoformat(day):%a %d %b})")
                (overdue if day < today else due_today if day == today else upcoming).append(item)
            else:
                undated += 1
        lines = []
        for label, items in (("overdue", overdue), ("today", due_today), ("upcoming", upcoming)):
            if items:
                lines.append(f"{label}: " + "; ".join(text for _, text in sorted(items)[:6]))
        lines.append(f"{undated} more open tasks without a date" if undated else "no undated tasks")
        return "\n".join(lines)

    async def sync_tasks(ctx: Context) -> str:
        from tars.tools.keys import press_keys

        ctx.actions.append("superproductivity sync")
        if not ctx.desktop:
            return "synced Super Productivity (dry run)"
        if not await _sp_up():
            await _sp_ready(ctx)
            await asyncio.sleep(2)  # window up after the API
        out = await press_keys(ctx, "ctrl+s", window="super productivity")  # its Sync shortcut
        return out.replace("pressed ctrl+s", "pressed Sync (Ctrl+S)")

    async def termius_connect(ctx: Context, host: str) -> str:
        app = apps.apps["termius"]
        ctx.actions.append(f"termius connect {host}")
        if not ctx.desktop:
            return f"connecting to {host} in Termius (dry run)"
        async with Atspi() as a:
            hosts = await _termius_hosts(a)
            if not hosts:
                launch(ctx, app)
                for _ in range(20):  # Termius takes a few seconds to show its host list
                    await asyncio.sleep(1)
                    if hosts := await _termius_hosts(a):
                        break
            if not hosts:
                return (
                    "error: Termius opened but its host list isn't showing; read_screen to see why"
                )
            match = difflib.get_close_matches(host.lower().strip(), list(hosts), n=1, cutoff=0.6)
            if not match:
                return f"error: no host {host!r} in Termius; it has: {', '.join(hosts)}"
            result = await a.click(hosts[match[0]])
        return f"{result} (Termius; read_screen to confirm the session opened)"

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
    reg.tool("termius_connect", "Open Termius and connect to one of the user's saved hosts (e.g. ada, turing).",
             obj(["host"], host={"type": "string"}), tier=Tier.T1, speak="Connecting")(termius_connect)  # fmt: skip
    reg.tool(
        "sync_tasks", "Sync Super Productivity (its Sync button).", tier=Tier.T1, speak="Syncing"
    )(sync_tasks)
    reg.tool("list_tasks", "The user's open tasks in Super Productivity: overdue, today, upcoming. "
             "Use for 'what's my next task', 'anything overdue?'.", speak="Checking your tasks")(list_tasks)  # fmt: skip
    reg.tool("list_apps", "The user's apps and what each is for.")(list_apps)
