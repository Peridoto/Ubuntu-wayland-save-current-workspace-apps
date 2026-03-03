# Ubuntu Wayland — Save & Restore Workspace Apps

Save and restore your open windows across virtual desktops on **GNOME 49+ / Wayland**.  
Built for systems where suspend/hibernate doesn't work — shut down cleanly and pick up where you left off.

## What it does

1. **Save**: Records every open window — app type, workspace, file/folder, geometry — to a JSON file.
2. **Restore**: Re-launches each app and moves windows back to their correct virtual desktop via D-Bus.

## Components

| Path | Description |
|------|-------------|
| `extension/` | GNOME Shell extension (`session-saver@pc`) — exposes window list & workspace-move methods via D-Bus |
| `scripts/session-save.py` | Saves current session to `~/.config/session-saver/session.json` |
| `scripts/session-restore.py` | Restores session: launches apps, moves windows to correct workspaces |
| `desktop/` | `.desktop` shortcuts for one-click save/restore |

## Supported apps

- **Google Chrome / Brave / Edge** (tabs restore automatically, windows moved by page title)
- **GNOME Text Editor** (re-opens specific files, matched by filename)
- **Nautilus** (re-opens specific directories, resolved from title including `/opt`, `/mnt`)
- **VS Code** (folder extracted from title for snap installs)
- **Ptyxis** (GNOME 49 default terminal)
- **Telegram, KeePassXC, MetaTrader, GNOME Terminal, Console**
- **Generic apps** (fallback via command + args)

## Requirements

- Ubuntu 25.10+ (or any distro with GNOME Shell 49+)
- Wayland session
- Python 3
- `gdbus` (comes with GLib, installed by default)

## Installation

```bash
# Clone
git clone git@github.com:Peridoto/Ubuntu-wayland-save-current-workspace-apps.git
cd Ubuntu-wayland-save-current-workspace-apps

# Run installer
chmod +x install.sh
./install.sh
```

Then **log out and log back in** (required for GNOME to discover the new extension).

## Usage

- Click **"Guardar Sesión"** on your desktop to save.
- Click **"Restaurar Sesión"** after reboot to restore.
- Check `~/.config/session-saver/restore.log` for details after a restore.

## How it works

The GNOME Shell extension exposes 4 D-Bus methods:

| Method | Description |
|--------|-------------|
| `GetWindows()` | Returns JSON array of all normal windows with workspace, title, wm_class, pid, geometry |
| `MoveWindowToWorkspace(pid, wmClass, wsIndex)` | Move window by PID |
| `MoveWindowByTitle(wmClass, titleSubstring, wsIndex)` | Move window matching title substring |
| `MoveAllByClass(wmClass, wsIndex)` | Move all windows of a class |

The restore script uses a **3-pass strategy** with delays to handle slow-launching apps, and prefers `MoveWindowByTitle` for multi-window apps (Chrome, VS Code, TextEditor, Nautilus) to avoid moving the wrong window.

## Tested on

- Ubuntu 25.10 (Questing), GNOME Shell 49.0, Wayland
- AMD Ryzen 9 5900X, RX 6700 XT, Gigabyte B550M DS3H
- 5 static workspaces

## Support the Development ☕

Developing for Wayland and GNOME Shell requires constant maintenance to keep up with new releases. If this extension saves you time and improves your workflow, please consider supporting my work:

[![Buy Me A Coffee](https://img.shields.shields.github.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/peridoto)

## License

GPL-3.0 license
