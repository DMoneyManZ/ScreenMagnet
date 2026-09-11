#!/usr/bin/env bash
# Per-user desktop installation of a checksum-verified ScreenMagnet AppImage.
# Never launches the application, extracts executable contents, or starts a cast.
set -euo pipefail

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'HELP'
Usage: bash install-appimage.sh [PATH/ScreenMagnet-x86_64.AppImage]
       bash install-appimage.sh --uninstall

Default input: ScreenMagnet-x86_64.AppImage beside this script.
Requires its .sha256 file (or SHA256SUMS) and screenmagnet.svg beside the download.
Installs the verified AppImage, launcher, and icon for your user without sudo.
The launcher uses AppImage extract-and-run mode, so FUSE is not required.
Uninstall removes these installed files and retains preferences and pairing data.
HELP
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --uninstall) [ "$#" -eq 1 ] || fail '--uninstall takes no path argument' ;;
    --*) fail "Unknown option: $1" ;;
esac
[ "$#" -le 1 ] || fail 'Expected at most one AppImage path'
[ "$EUID" -ne 0 ] || fail 'Run as your normal desktop user, without sudo'

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
case "$DATA_HOME" in /*) ;; *) fail 'XDG_DATA_HOME must be an absolute path' ;; esac
case "$DATA_HOME" in *$'\n'*|*$'\r'*|*$'\t'*) fail 'Control characters in the data path are unsupported' ;; esac
APP_DIR="$DATA_HOME/screenmagnet"
APPIMAGE="$APP_DIR/ScreenMagnet-x86_64.AppImage"
WRAPPER="$APP_DIR/screenmagnet"
ENTRY="$DATA_HOME/applications/screenmagnet.desktop"
ICON="$DATA_HOME/icons/hicolor/scalable/apps/screenmagnet.svg"
[ ! -L "$APP_DIR" ] || fail "Refusing a symbolic-link application directory: $APP_DIR"

refresh_desktop() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

if [ "${1:-}" = --uninstall ]; then
    rm -f -- "$APPIMAGE" "$WRAPPER"
    # Do not remove a launcher that was subsequently replaced by source setup.
    if [ -f "$ENTRY" ] && grep -qx 'X-ScreenMagnet-Install=appimage' "$ENTRY"; then
        rm -f -- "$ENTRY" "$ICON"
    fi
    rmdir -- "$APP_DIR" 2>/dev/null || true
    refresh_desktop
    printf '%s\n' 'Removed the AppImage and its desktop integration. Preferences and pairing data retained.'
    exit 0
fi

INPUT="${1:-$HERE/ScreenMagnet-x86_64.AppImage}"
[ -s "$INPUT" ] && [ -f "$INPUT" ] || fail "AppImage not found or empty: $INPUT"
SOURCE_DIR="$(cd -- "$(dirname -- "$INPUT")" && pwd)"
SOURCE_NAME="$(basename -- "$INPUT")"
INPUT="$SOURCE_DIR/$SOURCE_NAME"
CHECKSUM="$INPUT.sha256"
if [ ! -f "$CHECKSUM" ]; then CHECKSUM="$SOURCE_DIR/SHA256SUMS"; fi
[ -f "$CHECKSUM" ] || fail "Missing checksum: $INPUT.sha256 (or SHA256SUMS)"

# Accept only an unambiguous sha256sum record for this exact input filename.
EXPECTED=''
MATCHES=0
while IFS= read -r LINE || [ -n "$LINE" ]; do
    LINE="${LINE%$'\r'}"
    HASH="${LINE%% *}"
    [[ "$HASH" =~ ^[0-9a-fA-F]{64}$ ]] || continue
    REST="${LINE#"$HASH"}"
    case "$REST" in '  '*|' *'*) ;; *) continue ;; esac
    [ "${REST:2}" = "$SOURCE_NAME" ] || continue
    EXPECTED="${HASH,,}"
    MATCHES=$((MATCHES + 1))
done < "$CHECKSUM"
[ "$MATCHES" -eq 1 ] || fail 'Checksum must contain exactly one record naming the selected AppImage'

SOURCE_ICON=''
for CANDIDATE in "$SOURCE_DIR/screenmagnet.svg" "$HERE/screenmagnet.svg" "$HERE/../../app/assets/screenmagnet.svg"; do
    if [ -s "$CANDIDATE" ] && [ -f "$CANDIDATE" ]; then SOURCE_ICON="$CANDIDATE"; break; fi
done
[ -n "$SOURCE_ICON" ] || fail 'Download screenmagnet.svg beside the AppImage before installing'

mkdir -p -- "$DATA_HOME"
WORK="$(mktemp -d "$DATA_HOME/.screenmagnet-install.XXXXXXXX")"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
# Verify the copy that will actually be installed, before touching existing files.
cp -- "$INPUT" "$WORK/AppImage"
ACTUAL="$(sha256sum < "$WORK/AppImage")"
ACTUAL="${ACTUAL%% *}"
[ "$ACTUAL" = "$EXPECTED" ] || fail 'AppImage checksum mismatch; existing installation was not changed'
cp -- "$SOURCE_ICON" "$WORK/screenmagnet.svg"
cat > "$WORK/screenmagnet" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Use the FUSE-independent path consistently; do not retry arbitrary app errors.
exec "$HERE/ScreenMagnet-x86_64.AppImage" --appimage-extract-and-run "$@"
WRAPPER

# Desktop Entry string escaping occurs before Exec argument unquoting.
EXEC_VALUE="$WRAPPER"
EXEC_VALUE="${EXEC_VALUE//\\/\\\\}"
EXEC_VALUE="${EXEC_VALUE//\"/\\\"}"
EXEC_VALUE="${EXEC_VALUE//\$/\\\$}"
EXEC_VALUE="${EXEC_VALUE//\`/\\\`}"
EXEC_VALUE="${EXEC_VALUE//\\/\\\\}"
EXEC_VALUE="${EXEC_VALUE//%/%%}"
# '=' is disallowed in the executable name, but permitted in a quoted argument.
if [[ "$WRAPPER" == *=* ]]; then EXEC_LINE="Exec=bash \"$EXEC_VALUE\""; else EXEC_LINE="Exec=\"$EXEC_VALUE\""; fi
cat > "$WORK/screenmagnet.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=ScreenMagnet
Comment=Send your screen to a nearby AirPlay display
$EXEC_LINE
Icon=screenmagnet
Terminal=false
Categories=AudioVideo;Network;
StartupNotify=false
X-ScreenMagnet-Install=appimage
DESKTOP
chmod 755 "$WORK/AppImage" "$WORK/screenmagnet"
chmod 644 "$WORK/screenmagnet.svg" "$WORK/screenmagnet.desktop"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$WORK/screenmagnet.desktop"
fi
mkdir -p -- "$APP_DIR" "$(dirname -- "$ENTRY")" "$(dirname -- "$ICON")"
for TARGET in "$APPIMAGE" "$WRAPPER" "$ENTRY" "$ICON"; do
    [ ! -d "$TARGET" ] || fail "Expected a file, found directory: $TARGET"
done
mv -f -- "$WORK/AppImage" "$APPIMAGE"
mv -f -- "$WORK/screenmagnet" "$WRAPPER"
mv -f -- "$WORK/screenmagnet.svg" "$ICON"
mv -f -- "$WORK/screenmagnet.desktop" "$ENTRY"
refresh_desktop
printf 'Installed: %s\nLauncher: %s\n' "$APPIMAGE" "$ENTRY"
printf '%s\n' 'Open ScreenMagnet from your application menu when ready. No app or cast was started.'
