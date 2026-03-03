#!/usr/bin/env python3
"""session-restore.py — Restaura la sesión GNOME desde el JSON guardado.

Lee ~/.config/session-saver/session.json, lanza las aplicaciones y las
mueve al escritorio virtual correcto vía la extensión session-saver@pc.

Usa MoveWindowByTitle (wm_class + substring del título) para emparejar
ventanas de forma robusta después de lanzar las apps.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────
CONFIG_DIR   = Path.home() / '.config' / 'session-saver'
SESSION_FILE = CONFIG_DIR / 'session.json'
LOG_FILE     = CONFIG_DIR / 'restore.log'

DBUS_DEST  = 'org.gnome.Shell'
DBUS_PATH  = '/org/gnome/Shell/Extensions/SessionSaver'
DBUS_IFACE = 'org.gnome.Shell.Extensions.SessionSaver'

SINGLE_INSTANCE = {'telegram', 'keepassxc', 'metatrader', 'antigravity'}

LAUNCH_DELAY = 0.6
SETTLE_WAIT  = 8


# ── Logging ────────────────────────────────────────────────────────
_log_lines = []
def log(msg):
    print(msg)
    _log_lines.append(msg)

def save_log():
    with open(LOG_FILE, 'w') as f:
        f.write('\n'.join(_log_lines) + '\n')


# ── D-Bus helpers ──────────────────────────────────────────────────
def dbus_call(method, *args):
    cmd = [
        'gdbus', 'call', '--session',
        '-d', DBUS_DEST, '-o', DBUS_PATH,
        '-m', f'{DBUS_IFACE}.{method}',
    ] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    log(f'    [dbus] {method}({", ".join(str(a) for a in args)}) '
        f'-> rc={r.returncode} out={r.stdout.strip()[:80]}')
    return r


def get_windows():
    r = dbus_call('GetWindows')
    if r.returncode != 0:
        return []
    raw = r.stdout.strip()
    if raw.startswith("('") and raw.endswith("',)"):
        json_str = raw[2:-3].replace("\\'", "'")
    elif raw.startswith("('"):
        idx = raw.rfind("',)")
        json_str = raw[2:idx].replace("\\'", "'") if idx > 0 else raw
    else:
        json_str = raw
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return []


def move_by_title(wm_class, title_sub, workspace):
    """Mueve la ventana con wm_class y titulo que contenga title_sub."""
    return dbus_call('MoveWindowByTitle', wm_class, title_sub, workspace)


def move_by_pid(pid, wm_class, workspace):
    """Mueve la ventana por PID."""
    return dbus_call('MoveWindowToWorkspace', pid, wm_class, workspace)


def move_all_by_class(wm_class, workspace):
    """Mueve TODAS las ventanas de una clase al escritorio."""
    return dbus_call('MoveAllByClass', wm_class, workspace)


# ── Comprobar si un comando existe ─────────────────────────────────
def which(cmd):
    return subprocess.run(['which', cmd], capture_output=True).returncode == 0


# ── Construir comando de lanzamiento ───────────────────────────────
def build_cmd(entry):
    at = entry.get('app_type', '')

    if at == 'chrome':
        c = ['google-chrome']
        if entry.get('profile'):
            c.append(f'--profile-directory={entry["profile"]}')
        return c

    if at == 'chrome-pwa':
        c = ['google-chrome']
        if entry.get('app_id'):
            c.append(f'--app-id={entry["app_id"]}')
        if entry.get('profile'):
            c.append(f'--profile-directory={entry["profile"]}')
        return c

    if at == 'brave':
        c = ['brave-browser']
        if entry.get('profile'):
            c.append(f'--profile-directory={entry["profile"]}')
        return c

    if at == 'edge':
        c = ['microsoft-edge']
        if entry.get('profile'):
            c.append(f'--profile-directory={entry["profile"]}')
        return c

    if at == 'edge-pwa':
        c = ['microsoft-edge']
        if entry.get('app_id'):
            c.append(f'--app-id={entry["app_id"]}')
        if entry.get('profile'):
            c.append(f'--profile-directory={entry["profile"]}')
        return c

    if at == 'antigravity':
        return ['antigravity']

    if at == 'vscode':
        c = ['code']
        if entry.get('folder'):
            c.append(entry['folder'])
        return c

    if at == 'nautilus':
        c = ['nautilus', '--new-window']
        d = entry.get('directory')
        if d:
            c.append(d)
        return c

    if at == 'text-editor':
        c = ['gnome-text-editor', '-n']
        f = entry.get('file')
        if f and os.path.isfile(f):
            c.append(f)
        return c

    if at in ('terminal', 'console'):
        return [entry.get('command', 'gnome-terminal')]

    if at == 'ptyxis':
        return ['ptyxis']

    if at == 'telegram':
        return ['telegram-desktop']

    if at == 'keepassxc':
        c = ['keepassxc']
        if entry.get('database'):
            c.append(entry['database'])
        return c

    if at == 'metatrader':
        return ['metatrader5']

    if at == 'generic':
        c = [entry.get('command', '')]
        c.extend(entry.get('args', []))
        return c

    return None


# ── Identificador para emparejar ventanas después del lanzamiento ──
def match_key(entry):
    """Genera un substring de título para emparejar vía MoveWindowByTitle."""
    at = entry.get('app_type', '')

    if at == 'nautilus':
        d = entry.get('directory', '')
        if d:
            # Nautilus muestra el nombre de la carpeta como título
            basename = os.path.basename(d) if d.startswith('/') else d
            # Nombres especiales
            specials = {
                str(Path.home()): 'Carpeta personal',
                str(Path.home() / 'Descargas'): 'Descargas',
                str(Path.home() / 'Documentos'): 'Documentos',
                str(Path.home() / 'Escritorio'): 'Escritorio',
                str(Path.home() / 'Imágenes'): 'Imágenes',
                str(Path.home() / 'Música'): 'Música',
                str(Path.home() / 'Vídeos'): 'Vídeos',
            }
            return specials.get(d, basename)
        return None

    if at == 'text-editor':
        f = entry.get('file', '')
        if f:
            return os.path.basename(f)
        return None

    # Navegadores: usar el título de la página (sin sufijo del navegador)
    if at in ('chrome', 'brave', 'edge'):
        title = entry.get('title', '')
        for suffix in (' - Google Chrome', ' - Brave', ' - Microsoft Edge',
                       ' – Google Chrome', ' – Brave', ' – Microsoft Edge'):
            if title.endswith(suffix):
                return title[:-len(suffix)]
        return title if title else None

    # VS Code: usar el nombre de la carpeta del título
    if at == 'vscode':
        title = entry.get('title', '')
        parts = title.split(' - ')
        if len(parts) >= 3 and parts[-1].strip() == 'Visual Studio Code':
            return parts[-2].strip()
        return None

    return None


# ── main ───────────────────────────────────────────────────────────
def main():
    if not SESSION_FILE.exists():
        log(f'No hay sesión guardada en {SESSION_FILE}')
        sys.exit(1)

    test = dbus_call('GetWindows')
    if test.returncode != 0:
        msg = 'Extension session-saver no disponible.'
        log(f'ERROR: {msg}')
        subprocess.run(['notify-send', '-i', 'dialog-error', 'Session Saver', msg])
        sys.exit(1)

    with open(SESSION_FILE) as f:
        session = json.load(f)

    log(f'Restaurando {len(session)} ventanas...\n')

    existing_windows = get_windows()
    existing_classes = {w.get('wm_class', '') for w in existing_windows}

    by_ws = {}
    for entry in session:
        ws = entry.get('workspace', 0)
        by_ws.setdefault(ws, []).append(entry)

    launched = []     # (entry, was_launched: bool)
    skipped  = []
    launched_dedup = set()  # browsers + VS Code: launch once, move by title

    # ── Fase 1: Lanzar apps ────────────────────────────────────────
    for ws in sorted(by_ws):
        log(f'--- Escritorio {ws} ---')
        for entry in by_ws[ws]:
            at       = entry.get('app_type', '?')
            wm_class = entry.get('wm_class', '')

            if at in SINGLE_INSTANCE and wm_class in existing_classes:
                for w in existing_windows:
                    if w.get('wm_class', '') == wm_class:
                        move_by_pid(w['pid'], wm_class, ws)
                        log(f'  Movida (ya abierta): {at} -> WS {ws}')
                        break
                continue

            # Dedup: browsers y VS Code se lanzan una sola vez
            # (restauran sus ventanas internamente)
            if at in ('chrome', 'brave', 'edge', 'vscode'):
                dedup_key = (at, entry.get('profile', ''))
                if dedup_key in launched_dedup:
                    launched.append((entry, False))
                    log(f'  Pendiente mover: {at} -> WS {ws}')
                    continue
                launched_dedup.add(dedup_key)

            if at == 'text-editor' and entry.get('draft_name') and not entry.get('file'):
                log(f'  OMITIDO borrador: {entry.get("draft_name","")}')
                skipped.append(entry)
                continue

            cmd = build_cmd(entry)
            if not cmd or not cmd[0]:
                log(f'  OMITIDO: sin comando para {at}')
                skipped.append(entry)
                continue

            if not which(cmd[0]):
                log(f'  OMITIDO: {cmd[0]} no encontrado')
                skipped.append(entry)
                continue

            label = at
            if entry.get('profile'):   label += f' [{entry["profile"]}]'
            if entry.get('directory'): label += f' -> {os.path.basename(entry["directory"])}'
            if entry.get('file'):      label += f' -> {os.path.basename(entry["file"])}'

            log(f'  Abriendo: {label}  (cmd: {" ".join(cmd)[:80]})')
            try:
                subprocess.Popen(cmd, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launched.append((entry, True))
                time.sleep(LAUNCH_DELAY)
            except Exception as ex:
                log(f'  ERROR lanzando: {ex}')
                skipped.append(entry)

    if not launched:
        log('\nNinguna ventana lanzada.')
        save_log()
        return

    # ── Fase 2: Esperar y mover ────────────────────────────────────
    log(f'\nEsperando {SETTLE_WAIT}s a que aparezcan las ventanas...')
    time.sleep(SETTLE_WAIT)

    def do_moves(pass_label=''):
        windows = get_windows()
        moved = 0
        moved_titles = set()  # evitar mover la misma ventana dos veces

        log(f'\n  Ventanas actuales ({pass_label}):')
        for w in windows:
            log(f'    WS {w["workspace"]}: {w["wm_class"]:30s} | {w["title"][:50]}')

        for entry, _ in launched:
            target_ws = entry.get('workspace', 0)
            if target_ws == 0:
                continue  # Ya están en WS 0 por defecto

            wm_class = entry.get('wm_class', '')
            at       = entry.get('app_type', '')
            mk       = match_key(entry)

            log(f'\n  Intentando mover: {at} -> WS {target_ws} (match_key={mk})')

            # Estrategia 1: MoveWindowByTitle (más precisa)
            if mk and mk not in moved_titles:
                r = move_by_title(wm_class, mk, target_ws)
                if '(true,)' in r.stdout:
                    moved += 1
                    moved_titles.add(mk)
                    log(f'    OK via MoveByTitle({wm_class}, "{mk}", {target_ws})')
                    continue
                else:
                    log(f'    FALLO MoveByTitle: {r.stdout.strip()}')

            # Apps multi-ventana: solo match por título, sin fallback PID
            # (evita mover la ventana equivocada)
            multi_window = at in ('chrome', 'brave', 'edge', 'vscode',
                                  'nautilus', 'text-editor')
            if multi_window:
                log(f'    (multi-ventana: omitido fallback PID)')
                continue

            # Estrategia 2: buscar por wm_class (solo apps de ventana única)
            candidates = [w for w in windows
                          if w.get('wm_class','') == wm_class
                          and w['workspace'] != target_ws
                          and w['title'] not in moved_titles]
            if candidates:
                c = candidates[0]
                r = move_by_pid(c['pid'], wm_class, target_ws)
                if '(true,)' in r.stdout:
                    moved += 1
                    moved_titles.add(c['title'])
                    log(f'    OK via MoveByPID({c["pid"]}, {target_ws})')
                else:
                    log(f'    FALLO MoveByPID: {r.stdout.strip()}')
            else:
                log(f'    Sin candidatos para {at} wm_class={wm_class}')

        return moved

    moved = do_moves('pasada 1')

    # Segunda pasada para apps lentas
    log('\nEsperando 4s para segunda pasada...')
    time.sleep(4)
    moved += do_moves('pasada 2')

    # Tercera pasada final
    log('\nEsperando 3s para tercera pasada...')
    time.sleep(3)
    moved += do_moves('pasada 3')

    log(f'\n{"="*50}')
    log(f'Hecho. Lanzadas: {sum(1 for _,l in launched if l)}, '
        f'movidas: {moved}, omitidas: {len(skipped)}')

    if skipped:
        log('Omitidas:')
        for s in skipped:
            log(f'  - {s.get("app_type","?")}: {s.get("title","")[:50]}')

    save_log()

    subprocess.run(['notify-send', '-i', 'view-refresh',
                    'Session Saver',
                    f'Restaurada: {sum(1 for _,l in launched if l)} apps, '
                    f'{moved} movidas. Log en {LOG_FILE}'])


if __name__ == '__main__':
    main()
