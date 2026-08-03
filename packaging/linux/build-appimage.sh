#!/usr/bin/env bash
# Build a Linux AppImage for ScreenMagnet. Must run on Linux (CI does this on
# ubuntu-latest; run it yourself on any Linux box with python3.13 and curl).
#
# Usage: packaging/linux/build-appimage.sh <path-to-doubletake-linux-binary>
#
# The doubletake binary itself is built separately -- it's pure Go with no
# cgo dependency, so a plain `GOOS=linux GOARCH=amd64 go build ./cmd/doubletake`
# after applying patches/0001-screenmagnet-fixes.patch to a checkout of
# omarroth/doubletake@8ccea5f is all that's needed. distrobox/podman are only
# required at *runtime*, on hosts (like SteamOS) with no H.264 encoder --
# never at build time.
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <path-to-doubletake-linux-binary>" >&2
    exit 1
fi
DOUBLETAKE_BIN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APPDIR="$HERE/AppDir"
DIST="$HERE/dist"

rm -rf "$APPDIR" "$DIST" "$HERE/build-venv" "$HERE/frozen" "$HERE/build"
mkdir -p "$APPDIR/usr/bin" "$DIST"

echo "=== 1/4 freezing the app with PyInstaller ==="
python3.13 -m venv "$HERE/build-venv"
"$HERE/build-venv/bin/pip" install --upgrade pip >/dev/null
"$HERE/build-venv/bin/pip" install PySide6==6.11.1 zeroconf==0.150.0 pyinstaller

"$HERE/build-venv/bin/pyinstaller" \
    --name ScreenMagnet \
    --onedir \
    --noconfirm \
    --add-data "$REPO/app/assets:assets" \
    --paths "$REPO/app" \
    --distpath "$HERE/frozen" \
    --workpath "$HERE/build" \
    --specpath "$HERE" \
    "$REPO/packaging/pyinstaller_entry.py"

cp -r "$HERE/frozen/ScreenMagnet/." "$APPDIR/usr/bin/"

echo "=== 2/4 bundling doubletake ==="
mkdir -p "$APPDIR/usr/bin/doubletake/bin"
cp "$DOUBLETAKE_BIN" "$APPDIR/usr/bin/doubletake/bin/doubletake"
chmod +x "$APPDIR/usr/bin/doubletake/bin/doubletake"

echo "=== 3/4 desktop integration ==="
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp "$REPO/app/screenmagnet.desktop" "$APPDIR/usr/share/applications/"
cp "$REPO/app/screenmagnet.desktop" "$APPDIR/screenmagnet.desktop"
cp "$REPO/app/assets/screenmagnet.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/screenmagnet.svg"
cp "$REPO/app/assets/screenmagnet.svg" "$APPDIR/screenmagnet.svg"

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(cd "$(dirname "$(readlink -f "${0}")")" && pwd)"
export SCREENMAGNET_DOUBLETAKE="$HERE/usr/bin/doubletake"
exec "$HERE/usr/bin/ScreenMagnet" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "=== 4/4 packaging the AppImage ==="
if [ ! -x "$HERE/appimagetool.AppImage" ]; then
    curl -fL -o "$HERE/appimagetool.AppImage" \
        https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$HERE/appimagetool.AppImage"
fi

ARCH=x86_64 "$HERE/appimagetool.AppImage" "$APPDIR" "$DIST/ScreenMagnet-x86_64.AppImage"
echo "Built $DIST/ScreenMagnet-x86_64.AppImage"
