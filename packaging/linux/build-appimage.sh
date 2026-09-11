#!/usr/bin/env bash
# Build a Linux AppImage for ScreenMagnet. Must run on Linux (CI does this on
# Ubuntu 22.04, with deb-src repositories enabled so bundled libraries have
# matching source packages). Python 3.13, Go, curl and apt/dpkg are build tools;
# they are not required to launch the finished AppImage.
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
if [ ! -f "$DOUBLETAKE_BIN" ] || [ ! -x "$DOUBLETAKE_BIN" ]; then
    echo "error: doubletake must be an executable file: $DOUBLETAKE_BIN" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APPDIR="$HERE/AppDir"
DIST="$HERE/dist"

rm -rf "$APPDIR" "$DIST" "$HERE/build-venv" "$HERE/frozen" "$HERE/build"
mkdir -p "$APPDIR/usr/bin" "$DIST"

# The official artifact is frozen with 3.13 for a stable build baseline. 3.14
# is also tested in CI for source runs. PyInstaller embeds the
# selected interpreter, so the finished AppImage never imports host Python.
if [ -n "${PYTHON:-}" ]; then
    PYTHON_BIN="$PYTHON"
else
    PYTHON_BIN=""
    for candidate in python3.13; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON_BIN" ] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    cat >&2 <<HINT
error: no supported Python interpreter found.

Use Python 3.13 (release baseline). These require no system-wide
installation when uv or pyenv is available:

    uv python install 3.13
    pyenv install 3.13         # then: pyenv shell 3.13

Or point at an existing install directly:

    PYTHON=/path/to/python3.13 $0 <doubletake-binary>
HINT
    exit 1
fi
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PYTHON_VERSION" in
    3.13) ;;
    *) echo "error: Python 3.13 required for release source staging; got $PYTHON_VERSION" >&2; exit 1 ;;
esac

echo "=== 1/4 freezing the app with PyInstaller ==="
"$PYTHON_BIN" -m venv "$HERE/build-venv"
"$HERE/build-venv/bin/pip" install --upgrade pip >/dev/null
"$HERE/build-venv/bin/pip" install -r "$HERE/requirements-build.txt"

RELEASE_DATA="${SCREENMAGNET_RELEASE_DATA:-$REPO/build/release-data}"
if [ ! -d "$RELEASE_DATA" ]; then
    SENDER_SOURCE="${SCREENMAGNET_DOUBLETAKE_SOURCE:-${XDG_CACHE_HOME:-$HOME/.cache}/screenmagnet/doubletake-src}"
    [ -f "$SENDER_SOURCE/vendor/modules.txt" ] || {
        echo "Matching sender source/vendor required. Run install-doubletake.sh or set SCREENMAGNET_DOUBLETAKE_SOURCE." >&2
        exit 1
    }
    export PATH="${XDG_DATA_HOME:-$HOME/.local/share}/screenmagnet/toolchain/go/bin:$PATH"
    "$HERE/build-venv/bin/python" "$REPO/packaging/stage_release_data.py" \
        --doubletake-source "$SENDER_SOURCE" --output "$RELEASE_DATA"
fi


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

RELEASE_DATA="${SCREENMAGNET_RELEASE_DATA:-$REPO/build/release-data}"
for required in source licenses THIRD-PARTY-NOTICES.md; do
    [ -e "$RELEASE_DATA/$required" ] || { echo "Missing release source/notices: $RELEASE_DATA/$required" >&2; exit 1; }
done
mkdir -p "$APPDIR/usr/share/screenmagnet"
cp -r "$RELEASE_DATA/." "$APPDIR/usr/share/screenmagnet/"
cp "$REPO/LICENSE" "$APPDIR/usr/share/screenmagnet/LICENSE"

# Account for the actual ELF libraries collected on this builder, including
# host GTK/GLib and the ICU runtime carried by Qt's wheel.
"$HERE/build-venv/bin/python" "$HERE/stage_system_sources.py" \
    --frozen "$HERE/frozen/ScreenMagnet" \
    --output "$APPDIR/usr/share/screenmagnet"


echo "=== 2/4 bundling doubletake ==="
mkdir -p "$APPDIR/usr/bin/doubletake/bin"
cp "$DOUBLETAKE_BIN" "$APPDIR/usr/bin/doubletake/bin/doubletake"
chmod +x "$APPDIR/usr/bin/doubletake/bin/doubletake"

echo "=== 3/4 desktop integration ==="
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$APPDIR/usr/share/metainfo"
cp "$HERE/screenmagnet-appimage.desktop" \
    "$APPDIR/usr/share/applications/screenmagnet.desktop"
cp "$HERE/screenmagnet-appimage.desktop" "$APPDIR/screenmagnet.desktop"
cp "$REPO/app/assets/screenmagnet.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/screenmagnet.svg"
cp "$REPO/app/assets/screenmagnet.svg" "$APPDIR/screenmagnet.svg"
cp "$HERE/io.github.DMoneyManZ.ScreenMagnet.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/io.github.DMoneyManZ.ScreenMagnet.metainfo.xml"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APPDIR/screenmagnet.desktop"
fi

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(cd "$(dirname "$(readlink -f "${0}")")" && pwd)"
# The AppImage mount/extraction directory is not guaranteed to be visible
# inside distrobox. Keep the bundled sender in the user's shared data directory
# so the SteamOS fallback can execute the same binary from its container.
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
RUNTIME_DIR="$DATA_HOME/screenmagnet/runtime/doubletake"
mkdir -p "$RUNTIME_DIR/bin"
if ! cmp -s "$HERE/usr/bin/doubletake/bin/doubletake" "$RUNTIME_DIR/bin/doubletake"; then
    install -m755 "$HERE/usr/bin/doubletake/bin/doubletake" "$RUNTIME_DIR/bin/doubletake"
fi
export SCREENMAGNET_DOUBLETAKE="$RUNTIME_DIR"
exec "$HERE/usr/bin/ScreenMagnet" "$@"
EOF
chmod +x "$APPDIR/AppRun"

APPIMAGE_RUNTIME="$("$HERE/build-venv/bin/python" "$HERE/stage_appimage_runtime.py" \
    --output "$APPDIR/usr/share/screenmagnet" --cache "$REPO/build/appimage-runtime-cache")"

"$HERE/build-venv/bin/python" "$HERE/package_source_archive.py" \
    --payload "$APPDIR/usr/share/screenmagnet" --dist "$DIST"

echo "=== 4/4 packaging the AppImage ==="
if [ ! -x "$HERE/appimagetool.AppImage" ]; then
    curl -fL -o "$HERE/appimagetool.AppImage" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$HERE/appimagetool.AppImage"
fi
APPIMAGETOOL_SHA256="a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0"
echo "$APPIMAGETOOL_SHA256  $HERE/appimagetool.AppImage" | sha256sum --check --status || {
    echo "error: appimagetool checksum mismatch; remove $HERE/appimagetool.AppImage and retry" >&2
    exit 1
}

# --appimage-extract-and-run: appimagetool is itself an AppImage, so running it
# normally needs libfuse.so.2. Ubuntu 22.04+ (and GitHub's ubuntu-latest runners)
# ship only FUSE 3, so the plain invocation dies with "dlopen(): error loading
# libfuse.so.2". This flag unpacks the tool and runs it directly -- no FUSE needed.
ARCH=x86_64 "$HERE/appimagetool.AppImage" --appimage-extract-and-run \
    --runtime-file "$APPIMAGE_RUNTIME" "$APPDIR" "$DIST/ScreenMagnet-x86_64.AppImage"
(
    cd "$DIST"
    sha256sum ScreenMagnet-x86_64.AppImage > ScreenMagnet-x86_64.AppImage.sha256
)
echo "Built $DIST/ScreenMagnet-x86_64.AppImage"
