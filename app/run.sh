#!/usr/bin/env bash
# Launch ScreenMagnet.
#
# The venv lives outside the repo (in ~/.local/share) because SteamOS has a
# read-only root and system-wide pip is not an option. It must be built with
# python3.13 -- the default python here is 3.14 and PySide6/torch publish no
# 3.14 wheels.
set -euo pipefail

VENV="${SCREENMAGNET_VENV:-$HOME/.local/share/screenmagnet/venv}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$VENV/bin/python" ]; then
    echo "venv missing at $VENV" >&2
    echo "create it with:" >&2
    echo "  python3.13 -m venv $VENV && $VENV/bin/pip install PySide6" >&2
    exit 1
fi

if ! "$VENV/bin/python" -c "import PySide6" 2>/dev/null; then
    echo "PySide6 not installed in $VENV" >&2
    echo "  $VENV/bin/pip install PySide6" >&2
    exit 1
fi

# Only one tray instance is useful.
if pgrep -f "screenmagnet(\.__main__)?$" >/dev/null 2>&1; then
    echo "ScreenMagnet already running." >&2
    exit 0
fi

cd "$HERE"
exec "$VENV/bin/python" -m screenmagnet "$@"
