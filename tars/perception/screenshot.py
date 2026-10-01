"""
Screenshots on Wayland through the xdg-desktop-portal Screenshot API (the only
sanctioned way for an app on GNOME). The first use may show GNOME's permission
dialog; after "Allow" it is remembered.
"""

import asyncio
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.asyncio import open_dbus_router

PORTAL = DBusAddress("/org/freedesktop/portal/desktop", "org.freedesktop.portal.Desktop",
                     "org.freedesktop.portal.Screenshot")  # fmt: skip


class ScreenshotError(Exception):
    pass


async def take_screenshot(timeout: float = 30) -> Path:
    """Full-screen PNG; returns its path (the portal saves it, usually in ~/Pictures)."""
    async with open_dbus_router(bus="SESSION") as router:
        token = "tars" + secrets.token_hex(6)
        sender = router.unique_name.lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request",
                         member="Response", path=handle)  # fmt: skip
        await router.send_and_get_reply(message_bus.AddMatch(rule))  # subscribe before asking
        with router.filter(rule) as responses:
            await router.send_and_get_reply(
                new_method_call(PORTAL, "Screenshot", "sa{sv}",
                                ("", {"handle_token": ("s", token), "interactive": ("b", False)}))
            )  # fmt: skip
            try:
                signal = await asyncio.wait_for(responses.get(), timeout)
            except TimeoutError as e:
                raise ScreenshotError("no answer from the screenshot portal") from e
    code, results = signal.body
    if code != 0:
        raise ScreenshotError(
            "screenshot refused or cancelled" if code == 1 else f"portal error {code}"
        )
    return Path(unquote(urlparse(results["uri"][1]).path))
