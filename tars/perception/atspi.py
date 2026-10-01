"""
Read and operate desktop apps through the AT-SPI accessibility tree (the same
interface screen readers use) over D-Bus, via jeepney. No pixels, no OCR: exact
names, roles, states and text, and semantic actions (click, set text).

Works on Wayland. Coverage depends on the app: GTK, Qt, Firefox, LibreOffice
expose rich trees; Electron apps only with accessibility enabled; canvas apps
and games need the vision fallback (later in Phase 3).
"""

import asyncio
import logging
from dataclasses import dataclass, field

from jeepney import DBusAddress, Properties, new_method_call
from jeepney.io.asyncio import open_dbus_router

log = logging.getLogger("tars.atspi")

ACC = "org.a11y.atspi.Accessible"
ROOT = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")

# AT-SPI state bits (first uint32 of GetState)
ACTIVE, CHECKED, EDITABLE, ENABLED, FOCUSED, SELECTED, SENSITIVE, SHOWING, VISIBLE = (
    1,
    4,
    7,
    8,
    12,
    23,
    24,
    25,
    30,
)

INTERACTIVE = {
    "push button", "toggle button", "check box", "radio button", "menu item", "check menu item",
    "radio menu item", "link", "entry", "password text", "text", "combo box", "list item",
    "page tab", "slider", "spin button", "tree item", "table cell", "menu", "button", "switch",
    "icon", "editbar", "search box",
}  # fmt: skip
TEXTUAL = {
    "heading",
    "label",
    "static",
    "paragraph",
    "notification",
    "alert",
    "status bar",
    "caption",
}
SKIP = {"scroll bar", "separator", "filler", "panel", "redundant object", "invalid"}
RISKY_WORDS = ("send", "submit", "delete", "remove", "buy", "pay", "post", "publish", "confirm",
               "install", "uninstall", "format", "empty trash", "sign out", "log out", "transfer")  # fmt: skip


@dataclass
class Node:
    ref: tuple[str, str]  # (bus name, object path)
    role: str
    name: str
    states: set[int]
    interfaces: list[str]
    text: str = ""
    depth: int = 0
    children: list["Node"] = field(default_factory=list)

    @property
    def risky(self) -> bool:
        n = self.name.lower()
        return any(w in n for w in RISKY_WORDS)


class Atspi:
    """One connection to the accessibility bus. Use `async with Atspi() as a:`."""

    def __init__(self):
        self._session = None
        self._bus = None
        self.refs: dict[int, Node] = {}  # snapshot ids -> nodes, for actions
        self.labels: dict[str, int] = {}  # unique display name -> id (what the model uses)

    async def __aenter__(self) -> "Atspi":
        self._session = open_dbus_router(bus="SESSION")
        session = await self._session.__aenter__()
        reply = await session.send_and_get_reply(
            new_method_call(
                DBusAddress("/org/a11y/bus", "org.a11y.Bus", "org.a11y.Bus"), "GetAddress"
            )
        )
        self._bus_cm = open_dbus_router(bus=reply.body[0])
        self._bus = await self._bus_cm.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self._bus_cm.__aexit__(*exc)
        await self._session.__aexit__(*exc)

    async def _call(self, ref, iface, method, sig=None, body=(), timeout=2.0):
        msg = new_method_call(DBusAddress(ref[1], ref[0], iface), method, sig, body)
        reply = await asyncio.wait_for(self._bus.send_and_get_reply(msg), timeout)
        return reply.body

    async def _prop(self, ref, iface, name):
        msg = Properties(DBusAddress(ref[1], ref[0], iface)).get(name)
        reply = await asyncio.wait_for(self._bus.send_and_get_reply(msg), 2.0)
        return reply.body[0][1]

    async def _node(self, ref, depth: int) -> Node | None:
        try:
            role, name, states, ifaces = await asyncio.gather(
                self._call(ref, ACC, "GetRoleName"),
                self._prop(ref, ACC, "Name"),
                self._call(ref, ACC, "GetState"),
                self._call(ref, ACC, "GetInterfaces"),
            )
        except Exception:
            return None  # defunct object or unresponsive app
        bits = states[0][0] if states[0] else 0
        node = Node(
            ref,
            role[0],
            name or "",
            {i for i in range(32) if bits >> i & 1},
            ifaces[0],
            depth=depth,
        )
        if "org.a11y.atspi.Text" in node.interfaces and node.role in TEXTUAL | {
            "entry",
            "text",
            "document text",
        }:
            try:
                n = await self._prop(ref, "org.a11y.atspi.Text", "CharacterCount")
                node.text = (
                    await self._call(ref, "org.a11y.atspi.Text", "GetText", "ii", (0, min(n, 400)))
                )[0]
            except Exception:
                pass
        return node

    async def _children(self, ref) -> list[tuple[str, str]]:
        try:
            return list((await self._call(ref, ACC, "GetChildren"))[0])
        except Exception:
            return []

    async def windows(self) -> list[tuple[str, Node]]:
        """(app name, top-level window node) for every app; the active one first."""
        out = []
        for app_ref in await self._children(ROOT):
            try:
                app_name = await self._prop(app_ref, ACC, "Name")
            except Exception:
                continue
            for wref in await self._children(app_ref):
                node = await self._node(wref, 0)
                if node and node.role in ("frame", "window", "dialog", "alert", "file chooser"):
                    out.append((app_name or app_ref[0], node))
        out.sort(key=lambda w: ACTIVE not in w[1].states)
        return out

    async def tree(self, root: Node, max_nodes: int = 600, max_depth: int = 30) -> Node:
        """Breadth-first walk, fetching each level's nodes concurrently."""
        level, count = [root], 1
        while level and count < max_nodes:
            next_level = []
            kids_per_node = await asyncio.gather(*(self._children(n.ref) for n in level))
            for parent, kids in zip(level, kids_per_node):
                if parent.depth >= max_depth or SHOWING not in parent.states and parent is not root:
                    continue
                nodes = await asyncio.gather(*(self._node(k, parent.depth + 1) for k in kids[:200]))
                for n in nodes:
                    if n is None or count >= max_nodes:
                        continue
                    parent.children.append(n)
                    next_level.append(n)
                    count += 1
            level = next_level
        return root

    def render(self, root: Node, max_lines: int = 120) -> str:
        """Compact text the LLM sees: role 'unique name' [states] — only useful nodes."""
        self.refs.clear()
        self.labels.clear()
        lines: list[str] = []

        def visit(n: Node, indent: int, parent_label: str = ""):
            if len(lines) >= max_lines:
                return
            showing = SHOWING in n.states or n.depth == 0
            useful = n.role in INTERACTIVE or (n.role in TEXTUAL and (n.name or n.text))
            if n.role == "label" and (n.name or n.text) == parent_label:
                useful = False  # a button's own caption repeats its name
            if showing and useful and n.role not in SKIP:
                nid = len(self.refs) + 1
                self.refs[nid] = n
                flags = [label for bit, label in ((FOCUSED, "focused"), (CHECKED, "checked"),
                         (SELECTED, "selected")) if bit in n.states]  # fmt: skip
                if ENABLED not in n.states and SENSITIVE not in n.states and n.role in INTERACTIVE:
                    flags.append("disabled")
                label = n.name or n.text[:80] or f"unnamed {n.role}"
                key, k = label, 2
                while key in self.labels:  # repeated names get "(2)", "(3)"...
                    key, k = f"{label} ({k})", k + 1
                self.labels[key] = nid
                text = (
                    f" = {n.text[:120]!r}"
                    if n.text and n.text != n.name and n.role != "label"
                    else ""
                )
                lines.append(
                    f"{'  ' * indent}{n.role} {key!r}{text}{' [' + ', '.join(flags) + ']' if flags else ''}"
                )
                indent += 1
                parent_label = label
            for c in n.children:
                visit(c, indent, parent_label)

        visit(root, 0)
        more = "\n… (more elements not shown)" if len(lines) >= max_lines else ""
        return "\n".join(lines) + more

    async def doc_url(self, root: Node) -> str | None:
        """URL of the web page in a browser window (Document interface DocURL)."""

        def find(n: Node) -> Node | None:
            if (
                n.role in ("document web", "document frame")
                and "org.a11y.atspi.Document" in n.interfaces
            ):
                return n
            return next((d for c in n.children if (d := find(c))), None)

        doc = find(root)
        if doc is None:
            return None
        try:
            return (
                await self._call(
                    doc.ref, "org.a11y.atspi.Document", "GetAttributeValue", "s", ("DocURL",)
                )
            )[0] or None
        except Exception:
            return None

    async def click(self, node: Node) -> str:
        if "org.a11y.atspi.Action" not in node.interfaces:
            return f"error: {node.role} {node.name!r} has no click action"
        n = await self._prop(node.ref, "org.a11y.atspi.Action", "NActions")
        names = [
            (await self._call(node.ref, "org.a11y.atspi.Action", "GetName", "i", (i,)))[0]
            for i in range(n)
        ]
        idx = next(
            (
                i
                for i, a in enumerate(names)
                if a in ("click", "press", "activate", "jump", "toggle", "open")
            ),
            0,
        )
        ok = (await self._call(node.ref, "org.a11y.atspi.Action", "DoAction", "i", (idx,)))[0]
        return str(
            f"{names[idx] if names else 'action'} on {node.role} {node.name!r}: {'done' if ok else 'failed'}"
        )

    async def set_text(self, node: Node, text: str) -> str:
        if "org.a11y.atspi.EditableText" not in node.interfaces:
            return f"error: {node.role} {node.name!r} is not editable"
        ok = (
            await self._call(
                node.ref, "org.a11y.atspi.EditableText", "SetTextContents", "s", (text,)
            )
        )[0]
        return f"typed into {node.role} {node.name!r}: {'done' if ok else 'failed'}"
