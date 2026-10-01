"""System status, date/time and timers (read from /proc and /sys; no psutil)."""

import asyncio
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from tars.agent.tools import Context, Registry, Tier, obj

_timers: dict[int, tuple[str, float, asyncio.Task]] = {}


def _cpu_percent(interval: float = 0.25) -> float:
    def snap():
        vals = [int(v) for v in open("/proc/stat").readline().split()[1:]]
        return vals[3] + vals[4], sum(vals)  # idle + iowait, total

    i1, t1 = snap()
    time.sleep(interval)
    i2, t2 = snap()
    return float(100.0 * (1 - (i2 - i1) / max(1, t2 - t1)))


def _meminfo() -> dict[str, int]:
    out = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        out[k] = int(v.split()[0]) * 1024
    return out


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _battery() -> str | None:
    for bat in Path("/sys/class/power_supply").glob("BAT*"):
        cap, status = _read(f"{bat}/capacity"), _read(f"{bat}/status")
        if cap:
            return f"battery {cap}% ({(status or 'unknown').lower()})"
    return None


def _temps() -> list[str]:
    out = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        kind, temp = _read(f"{zone}/type"), _read(f"{zone}/temp")
        if kind in ("x86_pkg_temp", "TCPU", "acpitz") and temp:
            out.append(f"CPU {int(temp) // 1000}°C")
            break
    return out


def _gpu() -> str | None:
    if not shutil.which("nvidia-smi"):
        return None
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )  # fmt: skip
    if r.returncode != 0:
        return None
    util, used, total, temp = (x.strip() for x in r.stdout.split(","))
    return f"GPU {util}% busy, {used} of {total} MiB VRAM, {temp}°C"


def _top(n: int = 4) -> str:
    r = subprocess.run(
        ["ps", "-eo", "comm,%cpu,%mem", "--sort=-%cpu", "--no-headers"],
        capture_output=True, text=True, timeout=5,
    )  # fmt: skip
    rows = [line.split() for line in r.stdout.splitlines()[:n] if line.split()]
    return ", ".join(f"{c} {cpu}% CPU {mem}% RAM" for c, cpu, mem in rows)


def system_info(ctx: Context) -> str:
    mem = _meminfo()
    used = (mem["MemTotal"] - mem["MemAvailable"]) / 2**30
    st = os.statvfs(ctx.home)
    free_disk, total_disk = st.f_bavail * st.f_frsize / 2**30, st.f_blocks * st.f_frsize / 2**30
    up_h = float(open("/proc/uptime").read().split()[0]) / 3600
    ac = _read("/sys/class/power_supply/ADP1/online")
    parts = [
        f"CPU {_cpu_percent():.0f}% busy",
        f"RAM {used:.1f} of {mem['MemTotal'] / 2**30:.1f} GB used",
        f"disk {free_disk:.0f} of {total_disk:.0f} GB free",
        *_temps(),
        _gpu(),
        _battery(),
        ("on AC power" if ac == "1" else "on battery") if ac is not None else None,
        f"up {up_h:.1f} hours",
        f"top processes: {_top()}",
    ]
    return "; ".join(p for p in parts if p)


def now(ctx: Context) -> str:
    return datetime.now().astimezone().strftime("%A %d %B %Y, %I:%M %p %Z")


async def set_timer(
    ctx: Context, minutes: float = 0, seconds: float = 0, hours: float = 0, label: str = "timer"
) -> str:
    # Separate units so the model never has to convert ("one second" -> 0.0167 min).
    minutes = hours * 60 + minutes + seconds / 60
    if not 0 < minutes <= 24 * 60:
        return "error: the duration must be between 1 second and 24 hours"

    async def ring():
        await asyncio.sleep(minutes * 60)
        _timers.pop(tid, None)
        msg = f"Timer done: {label}."
        if ctx.desktop and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "TARS", "-u", "critical", "TARS", msg])
        if ctx.notify:
            ctx.notify(msg)

    tid = max(_timers, default=0) + 1
    _timers[tid] = (label, time.time() + minutes * 60, asyncio.create_task(ring()))
    secs = round(minutes * 60)
    parts = [(secs // 3600, "h"), (secs % 3600 // 60, "m"), (secs % 60, "s")]
    human = " ".join(f"{n}{u}" for n, u in parts if n)
    return f"timer {tid} set: {label}, {human}"


def list_timers(ctx: Context) -> str:
    if not _timers:
        return "no timers running"
    now_t = time.time()
    return "; ".join(
        f"{i}: {lbl}, {max(0, end - now_t) / 60:.1f} min left"
        for i, (lbl, end, _) in _timers.items()
    )


def cancel_timer(ctx: Context, timer_id: int) -> str:
    entry = _timers.pop(timer_id, None)
    if not entry:
        return f"no timer {timer_id}"
    entry[2].cancel()
    return f"cancelled timer {timer_id} ({entry[0]})"


def register(reg: Registry):
    reg.tool("get_system_info", "CPU, RAM, disk, temperatures, GPU, battery, power and top processes.",
             speak="Checking")(system_info)  # fmt: skip
    reg.tool("get_datetime", "Current local date and time.")(now)
    reg.tool(
        "set_timer", "Start a countdown timer or reminder. Give the duration in the units the user said.",
        obj([], hours={"type": "number"}, minutes={"type": "number"},
            seconds={"type": "number"}, label={"type": "string", "description": "what it is for"}),
        tier=Tier.T1,
    )(set_timer)  # fmt: skip
    reg.tool("list_timers", "Show running timers.")(list_timers)
    reg.tool("cancel_timer", "Cancel a running timer.", obj(["timer_id"], timer_id={"type": "integer"}),
             tier=Tier.T1)(cancel_timer)  # fmt: skip
