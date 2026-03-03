#!/usr/bin/env python3
"""session-save.py — Guarda el estado de la sesión GNOME actual.

Lee la lista de ventanas desde la extensión session-saver@pc (D-Bus),
enriquece cada entrada con /proc/PID/cmdline, y guarda en
~/.config/session-saver/session.json

Cada ventana se guarda como entrada independiente, incluyendo múltiples
ventanas del mismo proceso (ej. TextEditor, Nautilus, Chrome).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────
CONFIG_DIR   = Path.home() / '.config' / 'session-saver'
SESSION_FILE = CONFIG_DIR / 'session.json'

DBUS_DEST  = 'org.gnome.Shell'
DBUS_PATH  = '/org/gnome/Shell/Extensions/SessionSaver'
DBUS_IFACE = 'org.gnome.Shell.Extensions.SessionSaver'


# ── Helpers D-Bus ──────────────────────────────────────────────────
def dbus_call(method, *args):
    cmd = [
        'gdbus', 'call', '--session',
        '-d', DBUS_DEST, '-o', DBUS_PATH,
        '-m', f'{DBUS_IFACE}.{method}',
    ] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def parse_dbus_string(raw):
    """Extrae el string JSON del formato de salida gdbus: ('...',)"""
    if raw.startswith("('") and raw.endswith("',)"):
        s = raw[2:-3]
    elif raw.startswith("('"):
        idx = raw.rfind("',)")
        s = raw[2:idx] if idx > 0 else raw
    else:
        s = raw
    return s.replace("\\'", "'")


def get_windows():
    raw = dbus_call('GetWindows')
    return json.loads(parse_dbus_string(raw))


# ── /proc helpers ──────────────────────────────────────────────────
def read_cmdline(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().decode('utf-8', errors='replace').split('\x00')
    except (FileNotFoundError, PermissionError):
        return []


def find_nautilus_dirs(pid):
    """Intenta resolver directorios abiertos en Nautilus vía /proc/PID/fd."""
    dirs = set()
    try:
        fd_dir = f'/proc/{pid}/fd'
        for fd in os.listdir(fd_dir):
            try:
                target = os.readlink(f'{fd_dir}/{fd}')
                if (os.path.isdir(target)
                        and target.startswith(('/home/', '/mnt/', '/media/', '/tmp/'))
                        and '/.local/' not in target
                        and '/.config/' not in target
                        and '/.cache/' not in target):
                    dirs.add(target)
            except OSError:
                pass
    except (FileNotFoundError, PermissionError):
        pass
    return dirs


# ── Resolvers para títulos ─────────────────────────────────────────
NAUTILUS_SPECIAL = {
    'Inicio':             str(Path.home()),
    'Home':               str(Path.home()),
    'Carpeta personal':   str(Path.home()),
    'Escritorio':         str(Path.home() / 'Escritorio'),
    'Desktop':            str(Path.home() / 'Desktop'),
    'Documentos':         str(Path.home() / 'Documentos'),
    'Documents':          str(Path.home() / 'Documents'),
    'Descargas':          str(Path.home() / 'Descargas'),
    'Downloads':          str(Path.home() / 'Downloads'),
    'Imágenes':           str(Path.home() / 'Imágenes'),
    'Pictures':           str(Path.home() / 'Pictures'),
    'Música':             str(Path.home() / 'Música'),
    'Music':              str(Path.home() / 'Music'),
    'Vídeos':             str(Path.home() / 'Vídeos'),
    'Videos':             str(Path.home() / 'Videos'),
    'Papelera':           'trash:///',
    'Trash':              'trash:///',
    'Archivos recientes': 'recent:///',
    'Recent':             'recent:///',
}


def resolve_nautilus_title(title, known_dirs):
    """Mapea un título de ventana Nautilus a una ruta real."""
    if title in NAUTILUS_SPECIAL:
        return NAUTILUS_SPECIAL[title]
    if title.startswith('/') and os.path.isdir(title):
        return title
    for d in known_dirs:
        if os.path.basename(d) == title:
            return d
    for base in [Path.home(), Path('/mnt'), Path('/media'), Path('/opt')]:
        if not base.exists():
            continue
        try:
            for item in base.iterdir():
                if item.is_dir() and item.name == title:
                    return str(item)
                # Búsqueda un nivel más profundo (ej. /opt/anydesk/anydesk-7.1.1)
                if item.is_dir():
                    try:
                        for sub in item.iterdir():
                            if sub.is_dir() and sub.name == title:
                                return str(sub)
                    except PermissionError:
                        pass
        except PermissionError:
            pass
    return None


def resolve_text_editor_title(title):
    """Extrae la ruta del fichero del título de GNOME Text Editor.

    Formatos conocidos:
      "archivo.txt (~/Documentos) - Editor de texto"   -> ~/Documentos/archivo.txt
      "archivo.txt (Borrador) - Editor de texto"        -> borrador sin guardar
      "archivo.txt - Editor de texto"                   -> buscar en ~
    """
    title = re.sub(r'\s*-\s*(Editor de texto|Text Editor)\s*$', '', title).strip()
    m = re.match(r'^(.+?)\s+\((.+)\)$', title)
    if m:
        filename = m.group(1).strip()
        location = m.group(2).strip()
        if location in ('Borrador', 'Draft'):
            return {'type': 'draft', 'name': filename}
        if location.startswith('~/'):
            location = str(Path.home() / location[2:])
        full_path = os.path.join(location, filename)
        return {'type': 'file', 'path': full_path}
    if title:
        for base in [Path.home(), Path.home() / 'Documentos',
                     Path.home() / 'Escritorio', Path.home() / 'Descargas']:
            candidate = base / title
            if candidate.is_file():
                return {'type': 'file', 'path': str(candidate)}
        return {'type': 'draft', 'name': title}
    return None


# ── Clasificación ──────────────────────────────────────────────────
def classify(window, cmdline, nautilus_dirs):
    wm  = (window.get('wm_class') or '').lower()
    cmd_joined = '\x00'.join(cmdline).lower()
    title = window.get('title', '')

    e = {
        'workspace': window['workspace'],
        'title':     title,
        'wm_class':  window.get('wm_class', ''),
        'pid':       window['pid'],
        'geometry':  {
            'x': window['x'], 'y': window['y'],
            'w': window['width'], 'h': window['height'],
        },
    }

    def _profile():
        for a in cmdline:
            if a.startswith('--profile-directory='):
                return a.split('=', 1)[1]
        return None

    def _app_id():
        for a in cmdline:
            if a.startswith('--app-id='):
                return a.split('=', 1)[1]
        return None

    # ── Google Chrome ────────────────────────────────────
    if 'google-chrome' in wm or '/chrome/' in cmd_joined:
        aid = _app_id()
        if aid:
            e.update(app_type='chrome-pwa', command='google-chrome', app_id=aid)
        else:
            e.update(app_type='chrome', command='google-chrome')
        p = _profile()
        if p:
            e['profile'] = p
        return e

    # ── Brave ────────────────────────────────────────────
    if 'brave' in wm or 'brave-browser' in cmd_joined:
        e.update(app_type='brave', command='brave-browser')
        p = _profile()
        if p:
            e['profile'] = p
        return e

    # ── Microsoft Edge / PWA ─────────────────────────────
    if 'msedge' in wm or 'microsoft-edge' in wm or '/msedge/' in cmd_joined:
        aid = _app_id()
        if aid:
            e.update(app_type='edge-pwa', command='microsoft-edge', app_id=aid)
        else:
            e.update(app_type='edge', command='microsoft-edge')
        p = _profile()
        if p:
            e['profile'] = p
        return e

    # ── Antigravity ──────────────────────────────────────
    if 'antigravity' in wm or 'antigravity' in cmd_joined:
        e.update(app_type='antigravity', command='antigravity')
        return e

    # ── VS Code ──────────────────────────────────────────
    if 'code' in wm or '/snap/code/' in cmd_joined:
        e.update(app_type='vscode', command='code')
        for a in cmdline:
            if a.startswith('--folder-uri='):
                e['folder'] = a.split('=', 1)[1]
                break
            if not a.startswith('-') and os.path.isdir(a):
                e['folder'] = a
                break
        # Fallback: extraer carpeta del título
        # "file.py - FolderName - Visual Studio Code" → FolderName
        if 'folder' not in e:
            parts = title.split(' - ')
            if len(parts) >= 3 and parts[-1].strip() == 'Visual Studio Code':
                folder_name = parts[-2].strip()
                for base in [Path.home(), Path.home() / 'Proyectos',
                             Path('/mnt'), Path('/media')]:
                    if not base.exists():
                        continue
                    candidate = base / folder_name
                    if candidate.is_dir():
                        e['folder'] = str(candidate)
                        break
                    # Un nivel más profundo
                    try:
                        for sub in base.iterdir():
                            if sub.is_dir():
                                c2 = sub / folder_name
                                if c2.is_dir():
                                    e['folder'] = str(c2)
                                    break
                    except PermissionError:
                        pass
                    if 'folder' in e:
                        break
        return e

    # ── Nautilus (Archivos) — cada ventana independiente ─
    if 'nautilus' in wm or 'org.gnome.nautilus' in wm:
        e.update(app_type='nautilus', command='nautilus')
        resolved = resolve_nautilus_title(title, nautilus_dirs)
        if resolved:
            e['directory'] = resolved
        else:
            e['directory_guess'] = title
        return e

    # ── GNOME Text Editor — cada ventana independiente ───
    if 'text-editor' in wm or 'org.gnome.texteditor' in wm:
        e.update(app_type='text-editor', command='gnome-text-editor')
        info = resolve_text_editor_title(title)
        if info:
            if info['type'] == 'file':
                e['file'] = info['path']
            else:
                e['draft_name'] = info.get('name', '')
        return e

    # ── Terminal / Console / Ptyxis ───────────────────────
    if 'gnome-terminal' in wm or 'org.gnome.terminal' in wm:
        e.update(app_type='terminal', command='gnome-terminal')
        return e
    if 'kgx' in wm or 'org.gnome.console' in wm:
        e.update(app_type='console', command='kgx')
        return e
    if 'ptyxis' in wm or 'org.gnome.ptyxis' in wm:
        e.update(app_type='ptyxis', command='ptyxis')
        return e

    # ── Telegram ─────────────────────────────────────────
    if 'telegram' in wm:
        e.update(app_type='telegram', command='telegram-desktop')
        return e

    # ── KeePassXC ────────────────────────────────────────
    if 'keepass' in wm:
        e.update(app_type='keepassxc', command='keepassxc')
        for a in cmdline:
            if a.endswith('.kdbx'):
                e['database'] = a
                break
        return e

    # ── MetaTrader ───────────────────────────────────────
    if 'metatrader' in wm or 'mt5' in wm:
        e.update(app_type='metatrader', command='metatrader5')
        return e

    # ── Genérico ─────────────────────────────────────────
    if cmdline and cmdline[0]:
        e.update(app_type='generic', command=cmdline[0],
                 args=[a for a in cmdline[1:] if a])
        return e

    return None


# ── main ───────────────────────────────────────────────────────────
def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 0. Backup del JSON anterior (si existe)
    if SESSION_FILE.exists():
        import shutil
        backup = CONFIG_DIR / 'session.json.bak'
        shutil.copy2(SESSION_FILE, backup)

    # 1. Obtener ventanas de la extensión
    try:
        windows = get_windows()
    except Exception as ex:
        msg = (f'No se pudo contactar la extensión session-saver.\n'
               f'Está instalada y habilitada?\n  -> {ex}')
        print(f'ERROR: {msg}', file=sys.stderr)
        subprocess.run(['notify-send', '-i', 'dialog-error',
                        'Session Saver', msg])
        sys.exit(1)

    if isinstance(windows, dict) and 'error' in windows:
        print(f'ERROR extensión: {windows["error"]}', file=sys.stderr)
        sys.exit(1)

    print(f'Ventanas detectadas: {len(windows)}')

    # 2. Enriquecer con /proc
    cmdlines = {}
    nautilus_dirs = set()

    for w in windows:
        pid = w['pid']
        if pid not in cmdlines:
            cmdlines[pid] = read_cmdline(pid)
        if 'nautilus' in (w.get('wm_class') or '').lower():
            nautilus_dirs |= find_nautilus_dirs(pid)

    # 3. Clasificar — CADA ventana es una entrada individual
    session = []

    for w in windows:
        pid   = w['pid']
        entry = classify(w, cmdlines.get(pid, []), nautilus_dirs)
        if not entry:
            continue

        # Filtrar terminales que se usaron para session-save/restore
        title_lower = entry.get('title', '').lower()
        if entry.get('app_type') in ('ptyxis', 'terminal', 'console', 'generic'):
            args_str = ' '.join(entry.get('args', [])).lower()
            cmd_str = entry.get('command', '').lower()
            if ('session-save' in title_lower or 'session-restore' in title_lower
                    or 'session-save' in args_str or 'session-restore' in args_str):
                continue

        session.append(entry)

    session.sort(key=lambda x: x.get('workspace', 0))

    # 4. Deduplicar: navegadores con mismo perfil en el MISMO escritorio
    #    Chrome restaura sus pestañas automáticamente, solo necesitamos
    #    lanzarlo una vez por perfil.  Pero si hay ventanas en DISTINTOS
    #    escritorios queremos una entrada por escritorio para poder moverlas.
    deduped = []
    seen_browser = set()
    for s in session:
        at = s.get('app_type', '')
        if at in ('chrome', 'brave', 'edge'):
            key = (at, s.get('profile', ''), s.get('workspace', 0))
            if key in seen_browser:
                continue
            seen_browser.add(key)
        deduped.append(s)
    session = deduped

    # 5. Guardar
    with open(SESSION_FILE, 'w') as f:
        json.dump(session, f, indent=2, ensure_ascii=False)

    # 6. Resumen
    print(f'\nSesión guardada en {SESSION_FILE}')
    print(f'Entradas: {len(session)}\n')
    for s in session:
        ws    = s.get('workspace', '?')
        at    = s.get('app_type', '?')
        extra = ''
        if 'profile' in s:
            extra += f' [{s["profile"]}]'
        if 'app_id' in s:
            extra += f' (PWA {s["app_id"][:12]}...)'
        if 'directory' in s:
            extra += f' -> {s["directory"]}'
        if 'folder' in s:
            extra += f' [{s["folder"]}]'
        if 'file' in s:
            extra += f' -> {s["file"]}'
        if 'draft_name' in s:
            extra += f' (borrador: {s["draft_name"]})'
        title = s.get('title', '')[:50]
        print(f'  WS {ws}: {at}{extra}  <<{title}>>')

    subprocess.run(['notify-send', '-i', 'document-save',
                    'Session Saver',
                    f'Sesión guardada: {len(session)} ventanas'])


if __name__ == '__main__':
    main()
