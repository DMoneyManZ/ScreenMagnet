#!/usr/bin/env bash
# Install (or remove) ScreenMagnet's desktop entry and icon for the current user.
#
# Without this, the app is only launchable from a terminal sitting in app/:
# `python -m screenmagnet` resolves the package via the current directory, and a
# desktop launcher starts in $HOME instead. The entry written here pins both the
# command and its working directory, so it works from a menu or dock.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
ENTRY="$APPS/screenmagnet.desktop"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$ENTRY" "$ICONS/screenmagnet.svg"
    update-desktop-database "$APPS" 2>/dev/null || true
    gtk-update-icon-cache -f -t "${ICONS%/scalable/apps}" 2>/dev/null || true
    echo "Removed $ENTRY"
    exit 0
fi

mkdir -p "$APPS" "$ICONS"
install -m644 "$REPO/app/assets/screenmagnet.svg" "$ICONS/screenmagnet.svg"

# run.sh already resolves the venv, checks PySide6 and enforces one instance.
sed -e "s|@EXEC@|$REPO/app/run.sh|" \
    -e "s|@WORKDIR@|$REPO/app|" \
    "$REPO/app/screenmagnet.desktop" > "$ENTRY"
chmod +x "$ENTRY"

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "${ICONS%/scalable/apps}" 2>/dev/null || true

command -v desktop-file-validate >/dev/null && desktop-file-validate "$ENTRY"
echo "Installed $ENTRY"
echo "  Exec=$REPO/app/run.sh"
