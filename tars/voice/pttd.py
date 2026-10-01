#!/usr/bin/python3
"""
tars-pttd — push-to-talk key watcher for Wayland.

Wayland does not let ordinary apps see global key presses, and joining the
`input` group would let every program you run read every keystroke. This
daemon is the narrow alternative: it runs as an isolated system service with
access to input devices only, watches for ONE trigger (Right Ctrl by default,
optionally a mouse side button), and tells connected clients nothing but:

    {"ptt": "down"}    trigger pressed: start recording
    {"ptt": "up"}      trigger released: stop and transcribe
    {"ptt": "cancel"}  another key was pressed while holding it (e.g. RCtrl+C):
                       it was a shortcut, throw the recording away

Other keystrokes are seen only inside this process and never leave it. It does
not grab devices, so Right Ctrl keeps working as Ctrl everywhere.

Standard library only (it runs on the system python, outside your venvs).
Installed by scripts/install_pttd.sh, which copies it to a root-owned path and
starts it through systemd socket activation, so only your user can connect.
"""

import argparse
import json
import os
import re
import select
import socket
import struct
import sys
import time

EV_KEY = 0x01
EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux (24 bytes)
TRIGGERS = {"KEY_RIGHTCTRL": 97, "KEY_RIGHTALT": 100, "BTN_SIDE": 0x113, "BTN_EXTRA": 0x114}
RESCAN_S = 2.0  # pick up keyboards/mice that (re)connect, e.g. a wireless dongle


class PttState:
    """Turns raw key events into down/up/cancel. Pure logic, no I/O."""

    def __init__(self, triggers: set[int]):
        self.triggers = triggers
        self.held: int | None = None  # trigger code currently held
        self.cancelled = False

    def feed(self, code: int, value: int) -> str | None:
        """value: 1 = press, 0 = release, 2 = autorepeat. Returns an event or None."""
        if value == 2:
            return None
        if code in self.triggers:
            if value == 1 and self.held is None:
                self.held, self.cancelled = code, False
                return "down"
            if value == 0 and code == self.held:
                self.held = None
                return None if self.cancelled else "up"
            return None
        # Keys and mouse buttons make it a shortcut; touch contacts (0x140+) don't.
        if value == 1 and code < 0x140 and self.held is not None and not self.cancelled:
            self.cancelled = True
            return "cancel"
        return None


def _bitmap_has(bitmap: str, code: int) -> bool:
    bits = 0
    for word in bitmap.split():
        bits = (bits << 64) | int(word, 16)
    return bool(bits >> code & 1)


def find_devices(triggers: set[int]) -> dict[str, str]:
    """event device path -> name, for devices that can emit any trigger key."""
    found = {}
    for block in open("/proc/bus/input/devices").read().split("\n\n"):
        name = re.search(r'N: Name="(.*)"', block)
        handler = re.search(r"H: Handlers=.*?(event\d+)", block)
        keys = re.search(r"B: KEY=(.*)", block)
        if not (name and handler and keys):
            continue
        if any(_bitmap_has(keys.group(1), t) for t in triggers):
            found[f"/dev/input/{handler.group(1)}"] = name.group(1)
    return found


def listening_socket() -> socket.socket:
    """The socket systemd passed us (socket activation), or a local one for testing."""
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and os.environ.get("LISTEN_FDS") == "1":
        return socket.socket(fileno=3)
    path = os.environ.get("TARS_PTTD_SOCKET", f"/run/user/{os.getuid()}/tars-pttd.sock")
    if os.path.exists(path):
        os.unlink(path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    os.chmod(path, 0o600)
    s.listen()
    return s


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trigger", default="KEY_RIGHTCTRL", help=f"comma list of {list(TRIGGERS)}")
    args = ap.parse_args()
    triggers = {TRIGGERS[t.strip()] for t in args.trigger.split(",")}
    state = PttState(triggers)
    server = listening_socket()
    clients: list[socket.socket] = []
    devices: dict[int, str] = {}  # fd -> path
    last_scan = 0.0

    def broadcast(event: str):
        line = (json.dumps({"ptt": event, "t": time.time()}) + "\n").encode()
        for c in clients[:]:
            try:
                c.sendall(line)
            except OSError:
                clients.remove(c)
                c.close()

    while True:
        now = time.monotonic()
        if now - last_scan > RESCAN_S:
            last_scan = now
            open_paths = set(devices.values())
            for path, name in find_devices(triggers).items():
                if path not in open_paths:
                    try:
                        devices[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
                        log(f"watching {path} ({name})")
                    except OSError as e:
                        log(f"cannot open {path}: {e}")
        readable, _, _ = select.select([server, *clients, *devices], [], [], RESCAN_S)
        for fd in readable:
            if fd is server:
                conn, _ = server.accept()
                clients.append(conn)
            elif isinstance(fd, socket.socket):  # a client hung up (they never send)
                if not fd.recv(64):
                    clients.remove(fd)
                    fd.close()
            else:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:  # device unplugged
                    log(f"lost {devices[fd]}")
                    os.close(fd)
                    del devices[fd]
                    continue
                for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, off)
                    if etype == EV_KEY and (event := state.feed(code, value)):
                        broadcast(event)


if __name__ == "__main__":
    main()
