"""
Keyboard input on Wayland through the xdg-desktop-portal RemoteDesktop API,
under TARS's own app id (org.tars.TARS).

The first session shows GNOME's "Allow remote interaction" dialog; the portal
then returns a restore token (persist_mode 2 = until revoked), kept 0600 in
~/.local/share/tars, so later sessions start without asking. While a session is
open GNOME shows its remote-control indicator in the top bar.

Keys are sent as X keysyms; Mutter picks the keycode and adds Shift for
capitals and symbols itself.
"""

import asyncio
import os
import secrets

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.asyncio import DBusRouter, open_dbus_router

from tars import TARS_HOME
from tars.perception.screenshot import APP_ID, REGISTRY, _ensure_desktop_file

TOKEN_FILE = TARS_HOME / "remote-desktop.token"
DESKTOP = "/org/freedesktop/portal/desktop"
RD = DBusAddress(DESKTOP, "org.freedesktop.portal.Desktop", "org.freedesktop.portal.RemoteDesktop")
KEYBOARD = 1

SPECIAL = {
    "enter": 0xFF0D, "return": 0xFF0D, "tab": 0xFF09, "escape": 0xFF1B, "esc": 0xFF1B,
    "backspace": 0xFF08, "delete": 0xFFFF, "space": 0x20, "home": 0xFF50, "end": 0xFF57,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "arrowleft": 0xFF51, "arrowup": 0xFF52, "arrowright": 0xFF53, "arrowdown": 0xFF54,
    "pageup": 0xFF55, "pagedown": 0xFF56, "insert": 0xFF63, "menu": 0xFF67,
    "ctrl": 0xFFE3, "control": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9, "super": 0xFFEB,
    "meta": 0xFFEB, "win": 0xFFEB,
    **{f"f{i}": 0xFFBE + i - 1 for i in range(1, 13)},
}  # fmt: skip
MODIFIERS = {0xFFE3, 0xFFE1, 0xFFE9, 0xFFEB}


class InputError(Exception):
    pass


def keysym(ch: str) -> int:
    if ch == "\n":
        return SPECIAL["enter"]
    if ch == "\t":
        return SPECIAL["tab"]
    cp = ord(ch)
    return cp if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF else 0x01000000 + cp


def parse_combo(combo: str) -> list[int]:
    """'ctrl+shift+t' -> [Control_L, Shift_L, t]; 'Enter' -> [Return]."""
    keys = []
    for part in combo.replace(" ", "").split("+"):
        low = part.lower()
        if low in SPECIAL:
            keys.append(SPECIAL[low])
        elif len(part) == 1:
            keys.append(keysym(low))
        else:
            raise InputError(f"unknown key {part!r}")
    if not keys:
        raise InputError("no key given")
    return keys


class Keyboard:
    """async with Keyboard() as kb: await kb.type("12*7"); await kb.combo("Enter")"""

    def __init__(self):
        self._router_cm = None
        self.router: DBusRouter | None = None
        self.session: str = ""

    async def __aenter__(self) -> "Keyboard":
        _ensure_desktop_file()
        self._router_cm = open_dbus_router(bus="SESSION")
        self.router = await self._router_cm.__aenter__()
        reply = await self.router.send_and_get_reply(
            new_method_call(REGISTRY, "Register", "sa{sv}", (APP_ID, {}))
        )
        if reply.header.message_type.name == "error":
            raise InputError(f"couldn't register TARS with the portal: {reply.body}")
        try:
            await self._start()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc):
        if self.router and self.session:
            session = DBusAddress(self.session, "org.freedesktop.portal.Desktop",
                                  "org.freedesktop.portal.Session")  # fmt: skip
            try:
                await self.router.send_and_get_reply(new_method_call(session, "Close"))
            except Exception:
                pass
        if self._router_cm:
            await self._router_cm.__aexit__(*exc)

    async def _request(self, method: str, sig: str, args: tuple, timeout: float = 60) -> dict:
        """Call a portal method that answers with a Request.Response signal."""
        assert self.router is not None
        token = "tars" + secrets.token_hex(6)
        sender = self.router.unique_name.lstrip(":").replace(".", "_")
        handle = f"{DESKTOP}/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                         member="Response", path=handle)  # fmt: skip
        await self.router.send_and_get_reply(message_bus.AddMatch(rule))
        options = args[-1] | {"handle_token": ("s", token)}
        with self.router.filter(rule) as responses:
            reply = await self.router.send_and_get_reply(
                new_method_call(RD, method, sig, (*args[:-1], options))
            )
            if reply.header.message_type.name == "error":
                raise InputError(f"{method}: {reply.body}")
            try:
                signal = await asyncio.wait_for(responses.get(), timeout)
            except TimeoutError as e:
                raise InputError(f"no answer from the portal ({method})") from e
        code, results = signal.body
        if code == 1:
            raise InputError("remote interaction was refused")
        if code != 0:
            raise InputError(
                f"the portal failed ({method}, code {code}); GNOME may need the dialog "
                "answered: run `python -m tars.perception.keyboard` once"
            )
        return dict(results)

    async def _start(self) -> None:
        res = await self._request("CreateSession", "a{sv}",
                                  ({"session_handle_token": ("s", "tars" + secrets.token_hex(4))},))  # fmt: skip
        self.session = res["session_handle"][1]
        opts: dict[str, tuple[str, object]] = {"types": ("u", KEYBOARD), "persist_mode": ("u", 2)}
        if TOKEN_FILE.exists():
            opts["restore_token"] = ("s", TOKEN_FILE.read_text().strip())
        await self._request("SelectDevices", "oa{sv}", (self.session, opts))
        res = await self._request("Start", "osa{sv}", (self.session, "", {}), timeout=120)
        if not res.get("devices", ("u", 0))[1] & KEYBOARD:
            raise InputError("keyboard access wasn't granted")
        if "restore_token" in res:  # a fresh one every time; the old one is spent
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(res["restore_token"][1])

    async def _key(self, sym: int, pressed: bool) -> None:
        assert self.router is not None
        await self.router.send_and_get_reply(
            new_method_call(RD, "NotifyKeyboardKeysym", "oa{sv}iu",
                            (self.session, {}, sym, 1 if pressed else 0))
        )  # fmt: skip

    async def tap(self, syms: list[int]) -> None:
        """Press keys in order, release in reverse (a chord like Ctrl+S)."""
        for s in syms:
            await self._key(s, True)
        await asyncio.sleep(0.01)
        for s in reversed(syms):
            await self._key(s, False)
        await asyncio.sleep(0.01)

    async def combo(self, combo: str) -> None:
        await self.tap(parse_combo(combo))

    async def type(self, text: str, delay: float = 0.008) -> None:
        for ch in text:
            await self.tap([keysym(ch)])
            await asyncio.sleep(delay)


def forget() -> None:
    """Drop the saved approval; the next session asks again."""
    TOKEN_FILE.unlink(missing_ok=True)


if __name__ == "__main__":  # one-time approval: python -m tars.perception.keyboard

    async def _main():
        async with Keyboard() as kb:
            await kb.tap([SPECIAL["shift"]])  # harmless: a lone Shift press
        print("keyboard access granted and remembered")

    asyncio.run(_main())
