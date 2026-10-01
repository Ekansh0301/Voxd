"""
Screenshots on Wayland through the xdg-desktop-portal Screenshot API (the only
sanctioned way for an app on GNOME).

TARS registers its own app id with the portal first. Without that, GNOME files
the "Allow" under the empty id shared by every non-Flatpak app, and Flameshot
etc. then get silent screenshots too. By default the permission is removed
again after each capture. GNOME 50 shows its "Allow" dialog only to the focused
app, and TARS has no window, so the permission is granted once by hand (see the
error message) and kept (config: screen.keep_screenshot_permission).
"""

import asyncio
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse

from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
from jeepney.io.asyncio import open_dbus_router

APP_ID = "org.tars.TARS"  # needs a matching .desktop file for the portal to accept it
DESKTOP_FILE = Path.home() / ".local/share/applications" / f"{APP_ID}.desktop"
REGISTRY = DBusAddress("/org/freedesktop/portal/desktop", "org.freedesktop.portal.Desktop",
                       "org.freedesktop.host.portal.Registry")  # fmt: skip
STORE = DBusAddress("/org/freedesktop/impl/portal/PermissionStore",
                    "org.freedesktop.impl.portal.PermissionStore",
                    "org.freedesktop.impl.portal.PermissionStore")  # fmt: skip
PORTAL = DBusAddress("/org/freedesktop/portal/desktop", "org.freedesktop.portal.Desktop",
                     "org.freedesktop.portal.Screenshot")  # fmt: skip


class ScreenshotError(Exception):
    pass


def _ensure_desktop_file() -> None:
    if not DESKTOP_FILE.exists():
        DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=TARS\nComment=Local voice assistant\n"
            "Exec=true\nNoDisplay=true\n"
        )


async def _forget_permission(router) -> None:
    try:
        await router.send_and_get_reply(
            new_method_call(STORE, "DeletePermission", "sss", ("screenshot", "screenshot", APP_ID))
        )
    except Exception:
        pass  # nothing stored


async def take_screenshot(timeout: float = 30, keep_permission: bool = True) -> Path:
    """Full-screen PNG; returns its path (the portal saves it, usually in ~/Pictures)."""
    _ensure_desktop_file()
    async with open_dbus_router(bus="SESSION") as router:
        # Must come before any other portal call on this connection.
        reply = await router.send_and_get_reply(
            new_method_call(REGISTRY, "Register", "sa{sv}", (APP_ID, {}))
        )
        if reply.header.message_type.name == "error":
            raise ScreenshotError(
                f"couldn't register TARS with the screenshot portal: {reply.body}"
            )
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
            finally:
                if not keep_permission:
                    await _forget_permission(router)
    code, results = signal.body
    if code != 0:
        raise ScreenshotError(
            "screenshot refused or cancelled"
            if code == 1
            else "TARS has no screenshot permission (GNOME only asks the focused app, and TARS has no "
            "window). Grant it once: busctl --user call org.freedesktop.impl.portal.PermissionStore "
            "/org/freedesktop/impl/portal/PermissionStore org.freedesktop.impl.portal.PermissionStore "
            f"SetPermission sbssas screenshot true screenshot {APP_ID} 1 yes"
        )
    return Path(unquote(urlparse(results["uri"][1]).path))
