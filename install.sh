#!/bin/bash
# install.sh — Instala session-saver en el sistema local
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

EXT_DIR="$HOME/.local/share/gnome-shell/extensions/session-saver@pc"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/$(xdg-user-dir DESKTOP 2>/dev/null || echo Escritorio)"
# Fallback if xdg-user-dir returned the full path
[[ "$DESKTOP_DIR" == "$HOME/$HOME"* ]] && DESKTOP_DIR="$(xdg-user-dir DESKTOP)"

echo "=== Session Saver — Instalación ==="
echo ""

# 1. Extension
echo "[1/4] Instalando extensión GNOME Shell..."
mkdir -p "$EXT_DIR"
cp "$SCRIPT_DIR/extension/extension.js" "$EXT_DIR/"
cp "$SCRIPT_DIR/extension/metadata.json" "$EXT_DIR/"
echo "  → $EXT_DIR"

# 2. Scripts
echo "[2/4] Instalando scripts..."
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/scripts/session-save.py" "$BIN_DIR/"
cp "$SCRIPT_DIR/scripts/session-restore.py" "$BIN_DIR/"
chmod +x "$BIN_DIR/session-save.py" "$BIN_DIR/session-restore.py"
echo "  → $BIN_DIR"

# 3. Desktop shortcuts
echo "[3/4] Creando accesos directos..."
cp "$SCRIPT_DIR/desktop/Guardar Sesión.desktop" "$DESKTOP_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/desktop/Restaurar Sesión.desktop" "$DESKTOP_DIR/" 2>/dev/null || true
# Trust the shortcuts (GNOME 45+)
gio set "$DESKTOP_DIR/Guardar Sesión.desktop" metadata::trusted true 2>/dev/null || true
gio set "$DESKTOP_DIR/Restaurar Sesión.desktop" metadata::trusted true 2>/dev/null || true
echo "  → $DESKTOP_DIR"

# 4. Enable extension
echo "[4/4] Habilitando extensión..."
CURRENT=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "[]")
if [[ "$CURRENT" != *"session-saver@pc"* ]]; then
    if [[ "$CURRENT" == "@as []" || "$CURRENT" == "[]" ]]; then
        gsettings set org.gnome.shell enabled-extensions "['session-saver@pc']"
    else
        NEW="${CURRENT%]*}, 'session-saver@pc']"
        gsettings set org.gnome.shell enabled-extensions "$NEW"
    fi
    echo "  → Extensión añadida a enabled-extensions"
else
    echo "  → Ya estaba habilitada"
fi

echo ""
echo "✓ Instalación completada."
echo ""
echo "IMPORTANTE: Cierra sesión y vuelve a entrar para que GNOME"
echo "cargue la extensión (requerido en Wayland)."
echo ""
echo "Después ya puedes usar los accesos directos del escritorio:"
echo "  • Guardar Sesión"
echo "  • Restaurar Sesión"
