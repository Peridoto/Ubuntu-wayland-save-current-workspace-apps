// session-saver@pc — GNOME Shell Extension (GNOME 49 / Wayland)
// Exposes window list & workspace-move via D-Bus for session save/restore.

import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE_XML = `
<node>
  <interface name="org.gnome.Shell.Extensions.SessionSaver">
    <method name="GetWindows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="MoveWindowToWorkspace">
      <arg type="i" direction="in" name="pid"/>
      <arg type="s" direction="in" name="wmClass"/>
      <arg type="i" direction="in" name="workspaceIndex"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="MoveWindowByTitle">
      <arg type="s" direction="in" name="wmClass"/>
      <arg type="s" direction="in" name="titleSubstring"/>
      <arg type="i" direction="in" name="workspaceIndex"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="MoveAllByClass">
      <arg type="s" direction="in" name="wmClass"/>
      <arg type="i" direction="in" name="workspaceIndex"/>
      <arg type="i" direction="out" name="count"/>
    </method>
    <method name="SetWindowGeometry">
      <arg type="s" direction="in" name="wmClass"/>
      <arg type="s" direction="in" name="titleSubstring"/>
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
      <arg type="i" direction="in" name="w"/>
      <arg type="i" direction="in" name="h"/>
      <arg type="b" direction="out" name="success"/>
    </method>
  </interface>
</node>`;

/* ------------------------------------------------------------------ */

class _SessionSaverDBus {
    GetWindows() {
        try {
            const windows = global.get_window_actors()
                .map(actor => {
                    const w = actor.meta_window;
                    if (w.get_window_type() !== Meta.WindowType.NORMAL)
                        return null;
                    const rect = w.get_frame_rect();
                    return {
                        title:            w.get_title() ?? '',
                        wm_class:         w.get_wm_class() ?? '',
                        wm_class_instance: w.get_wm_class_instance() ?? '',
                        pid:              w.get_pid(),
                        workspace:        w.get_workspace()?.index() ?? -1,
                        x: rect.x,  y: rect.y,
                        width: rect.width,  height: rect.height,
                    };
                })
                .filter(w => w !== null);
            return JSON.stringify(windows);
        } catch (e) {
            return JSON.stringify({error: e.message});
        }
    }

    MoveWindowToWorkspace(pid, wmClass, workspaceIndex) {
        try {
            for (const actor of global.get_window_actors()) {
                const w = actor.meta_window;
                if (w.get_window_type() !== Meta.WindowType.NORMAL)
                    continue;
                if (w.get_pid() === pid &&
                    (wmClass === '' || w.get_wm_class() === wmClass)) {
                    w.change_workspace_by_index(workspaceIndex, true);
                    return true;
                }
            }
            return false;
        } catch (_) {
            return false;
        }
    }

    MoveWindowByTitle(wmClass, titleSubstring, workspaceIndex) {
        try {
            for (const actor of global.get_window_actors()) {
                const w = actor.meta_window;
                if (w.get_window_type() !== Meta.WindowType.NORMAL)
                    continue;
                const cls = w.get_wm_class() ?? '';
                const title = w.get_title() ?? '';
                if (cls === wmClass && title.includes(titleSubstring)) {
                    w.change_workspace_by_index(workspaceIndex, true);
                    return true;
                }
            }
            return false;
        } catch (_) {
            return false;
        }
    }

    MoveAllByClass(wmClass, workspaceIndex) {
        let count = 0;
        try {
            for (const actor of global.get_window_actors()) {
                const w = actor.meta_window;
                if (w.get_window_type() !== Meta.WindowType.NORMAL)
                    continue;
                if ((w.get_wm_class() ?? '') === wmClass) {
                    w.change_workspace_by_index(workspaceIndex, true);
                    count++;
                }
            }
        } catch (_) {}
        return count;
    }

    SetWindowGeometry(wmClass, titleSubstring, x, y, w, h) {
        try {
            for (const actor of global.get_window_actors()) {
                const win = actor.meta_window;
                if (win.get_window_type() !== Meta.WindowType.NORMAL)
                    continue;
                const cls = win.get_wm_class() ?? '';
                const title = win.get_title() ?? '';
                if (cls === wmClass &&
                    (titleSubstring === '' || title.includes(titleSubstring))) {
                    // Unmaximize first so move/resize takes effect
                    if (win.get_maximized()) {
                        win.unmaximize(Meta.MaximizeFlags.BOTH);
                    }
                    win.move_resize_frame(false, x, y, w, h);
                    return true;
                }
            }
            return false;
        } catch (_) {
            return false;
        }
    }
}

/* ------------------------------------------------------------------ */

export default class SessionSaverExtension extends Extension {
    enable() {
        this._service = new _SessionSaverDBus();
        this._dbus = Gio.DBusExportedObject.wrapJSObject(
            Gio.DBusNodeInfo.new_for_xml(IFACE_XML).interfaces[0],
            this._service,
        );
        this._dbus.export(
            Gio.DBus.session,
            '/org/gnome/Shell/Extensions/SessionSaver',
        );
    }

    disable() {
        this._dbus?.unexport();
        this._dbus   = null;
        this._service = null;
    }
}
