// TARS windows: list open windows and focus one, for the local TARS assistant.
// D-Bus (session bus): org.tars.Windows at /org/tars/Windows
//   List() -> s       JSON array of {id, title, app, wm_class, pid, focused, minimized,
//                     x, y, width, height, workspace}
//   Activate(t id) -> b   focus that window (switching workspace / unminimizing)
// Nothing else: no input, no screen contents, no settings.

import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.tars.Windows">
    <method name="List">
      <arg type="s" direction="out" name="windows"/>
    </method>
    <method name="Activate">
      <arg type="t" direction="in" name="id"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
  </interface>
</node>`;

function windows() {
    return global.get_window_actors()
        .map(actor => actor.meta_window)
        .filter(w => w && !w.skip_taskbar);
}

export default class TarsWindows extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/tars/Windows');
        this._name = Gio.bus_own_name_on_connection(
            Gio.DBus.session, 'org.tars.Windows', Gio.BusNameOwnerFlags.NONE, null, null);
    }

    disable() {
        if (this._name) {
            Gio.bus_unown_name(this._name);
            this._name = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
    }

    List() {
        const tracker = Shell.WindowTracker.get_default();
        return JSON.stringify(windows().map(w => {
            const r = w.get_frame_rect();
            return {
                id: w.get_id(),
                title: w.get_title() ?? '',
                app: tracker.get_window_app(w)?.get_id() ?? '',
                wm_class: w.get_wm_class() ?? '',
                pid: w.get_pid(),
                focused: w.has_focus(),
                minimized: w.minimized,
                x: r.x, y: r.y, width: r.width, height: r.height,
                workspace: w.get_workspace()?.index() ?? -1,
            };
        }));
    }

    Activate(id) {
        const w = windows().find(win => win.get_id() === id);
        if (!w)
            return false;
        Main.activateWindow(w);
        return true;
    }
}
