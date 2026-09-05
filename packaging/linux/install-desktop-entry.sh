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

# Keep menu launches on the same dependency-aware path as terminal launches.
EXEC_VALUE="$(printf '%s' "$REPO/screenmagnet-linux.sh" | sed 's/[&|\\]/\\&/g')"
WORKDIR_VALUE="$(printf '%s' "$REPO/app" | sed 's/[&|\\]/\\&/g')"
sed -e "s|@EXEC@|$EXEC_VALUE|" \
    -e "s|@WORKDIR@|$WORKDIR_VALUE|" \
    "$REPO/app/screenmagnet.desktop" > "$ENTRY"
chmod +x "$ENTRY"

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "${ICONS%/scalable/apps}" 2>/dev/null || true

command -v desktop-file-validate >/dev/null && desktop-file-validate "$ENTRY"
echo "Installed $ENTRY"
echo "  Exec=bash $REPO/screenmagnet-linux.sh run-source"
