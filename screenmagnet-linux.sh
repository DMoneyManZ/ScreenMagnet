#!/usr/bin/env bash
# One Linux entry point for running, preparing, building, and testing ScreenMagnet.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="${SCREENMAGNET_VENV:-$DATA_HOME/screenmagnet/venv}"
DOUBLETAKE_DIR="${SCREENMAGNET_DOUBLETAKE:-$DATA_HOME/screenmagnet/doubletake}"
APPIMAGE_DEFAULT="$ROOT/packaging/linux/dist/ScreenMagnet-x86_64.AppImage"
APPIMAGE="${SCREENMAGNET_APPIMAGE:-$APPIMAGE_DEFAULT}"

say() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

os_id() {
    if [ -r /etc/os-release ]; then
        ( . /etc/os-release; printf '%s' "${ID:-unknown}" )
    else
        printf 'unknown'
    fi
}

python_ok() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,13),(3,14)) else 1)' \
        >/dev/null 2>&1
}

find_existing_python() {
    if [ -n "${PYTHON:-}" ] && have "$PYTHON" && python_ok "$PYTHON"; then
        command -v "$PYTHON"
        return
    fi
    local candidate
    for candidate in python3.13 python3.14; do
        if have "$candidate" && python_ok "$candidate"; then
            command -v "$candidate"
            return
        fi
    done
    return 1
}

find_python() {
    if find_existing_python; then
        return
    fi
    if have uv; then
        uv python install 3.13 >/dev/null
        uv python find 3.13
        return
    fi
    return 1
}

has_fuse2() {
    { ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2' || \
        [ -e /lib/x86_64-linux-gnu/libfuse.so.2 ] || \
        [ -e /usr/lib/x86_64-linux-gnu/libfuse.so.2 ]; } && \
        [ -r /dev/fuse ] && [ -w /dev/fuse ]
}

has_encoder() {
    have gst-inspect-1.0 || return 1
    local encoder
    for encoder in x264enc openh264enc vah264enc vaapih264enc; do
        gst-inspect-1.0 "$encoder" >/dev/null 2>&1 && return 0
    done
    return 1
}

doctor() {
    local failed=0 id
    id="$(os_id)"
    say "ScreenMagnet Linux doctor"
    printf 'OS: %s\n' "$id"
    printf 'Architecture: %s\n' "$(uname -m)"

    if [ "$(uname -m)" = x86_64 ]; then
        echo '[ok] x86_64 AppImage architecture'
    else
        echo '[warn] release AppImage is x86_64-only; source mode may still work'
    fi

    if [ -x "$APPIMAGE" ]; then
        echo "[ok] AppImage: $APPIMAGE"
    elif [ -f "$APPIMAGE" ]; then
        echo "[ok] AppImage found (launcher will make it executable): $APPIMAGE"
    else
        echo "[info] no local AppImage at $APPIMAGE; source mode remains available"
    fi

    if has_fuse2; then
        echo '[ok] FUSE 2 library and usable /dev/fuse available'
    else
        echo '[info] usable FUSE 2 absent; launcher will use AppImage extract-and-run'
    fi

    if have gst-launch-1.0 && has_encoder; then
        echo '[ok] native GStreamer and an H.264 encoder available'
    elif have distrobox && distrobox list 2>/dev/null | grep -q 'screenmagnet'; then
        echo '[ok] ScreenMagnet distrobox fallback available'
    else
        echo '[missing] install native GStreamer plugins or create the screenmagnet distrobox'
        failed=1
    fi

    if [ -x "$DOUBLETAKE_DIR/bin/doubletake" ]; then
        echo "[ok] source-mode doubletake: $DOUBLETAKE_DIR/bin/doubletake"
    else
        echo '[info] source-mode doubletake not built yet'
    fi

    if [ -x "$VENV/bin/python" ]; then
        echo "[ok] managed source venv: $VENV"
    elif find_existing_python >/dev/null 2>&1 || have uv; then
        echo '[ok] Python 3.13/3.14 is available for source setup'
    else
        echo '[info] source setup needs Python 3.13/3.14 or uv'
    fi

    return "$failed"
}

install_native_deps() {
    local id
    id="$(os_id)"
    say "Installing native capture dependencies for $id"
    case "$id" in
        ubuntu|debian|linuxmint|pop)
            sudo apt-get update
            sudo apt-get install -y \
                curl git x11-xserver-utils \
                libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
                libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
                libxcb-shape0 libxcb-util1 libxcb-xkb1 \
                gstreamer1.0-tools gstreamer1.0-plugins-base \
                gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
                gstreamer1.0-plugins-ugly
            ;;
        fedora)
            sudo dnf install -y \
                curl git xrandr libglvnd-egl libxkbcommon-x11 \
                xcb-util xcb-util-cursor xcb-util-image xcb-util-keysyms \
                xcb-util-renderutil xcb-util-wm \
                gstreamer1 gstreamer1-plugins-base \
                gstreamer1-plugins-good gstreamer1-plugins-bad-free \
                gstreamer1-plugins-ugly-free
            ;;
        arch|manjaro)
            sudo pacman -S --needed \
                curl git xorg-xrandr libglvnd libxkbcommon-x11 \
                xcb-util-cursor xcb-util-image xcb-util-keysyms \
                xcb-util-renderutil xcb-util-wm gstreamer gst-plugins-base \
                gst-plugins-good gst-plugins-bad gst-plugins-ugly
            ;;
        steamos)
            echo 'SteamOS has a read-only base system; use setup-steamos instead.' >&2
            return 1
            ;;
        *)
            echo "Unsupported package manager for $id." >&2
            echo 'Install GStreamer tools plus base/good/bad/ugly plugins and xrandr.' >&2
            return 1
            ;;
    esac
}

setup_steamos() {
    have distrobox || {
        echo 'distrobox is required on SteamOS. Install it, then rerun setup-steamos.' >&2
        return 1
    }
    if distrobox list 2>/dev/null | grep -q 'screenmagnet'; then
        echo 'The screenmagnet distrobox already exists.'
        return
    fi
    distrobox create --yes --name screenmagnet --image ubuntu:24.04 \
        --additional-packages \
        "gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly x11-xserver-utils"
}

setup_source() {
    [ -f "$ROOT/pyproject.toml" ] || {
        echo 'Source setup requires running this launcher from the repository root.' >&2
        return 1
    }
    local python
    python="$(find_python)" || {
        echo 'Python 3.13/3.14 or uv is required for source mode.' >&2
        return 1
    }
    say "Creating managed Python environment with $python"
    "$python" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/pip" install --editable "$ROOT"

    say "Building the pinned doubletake sender"
    SCREENMAGNET_DOUBLETAKE="$DOUBLETAKE_DIR" \
        "$ROOT/packaging/linux/install-doubletake.sh"
}

run_source() {
    [ -x "$VENV/bin/python" ] && [ -x "$DOUBLETAKE_DIR/bin/doubletake" ] || setup_source
    export SCREENMAGNET_VENV="$VENV"
    export SCREENMAGNET_DOUBLETAKE="$DOUBLETAKE_DIR"
    exec "$ROOT/app/run.sh" "${RUN_ARGS[@]}"
}

find_appimage() {
    if [ -f "$APPIMAGE" ]; then
        printf '%s' "$APPIMAGE"
        return
    fi
    local candidate
    candidate="$(find "$ROOT" -maxdepth 1 -type f -name 'ScreenMagnet*.AppImage' -print -quit)"
    [ -n "$candidate" ] && printf '%s' "$candidate"
}

run_appimage() {
    local artifact
    artifact="$(find_appimage)" || {
        echo 'No AppImage found beside the launcher or under packaging/linux/dist.' >&2
        return 1
    }
    chmod +x "$artifact"
    if has_fuse2; then
        exec "$artifact" "${RUN_ARGS[@]}"
    fi
    export APPIMAGE_EXTRACT_AND_RUN=1
    exec "$artifact" "${RUN_ARGS[@]}"
}

run_auto() {
    if find_appimage >/dev/null; then
        run_appimage
    else
        run_source
    fi
}

build_appimage() {
    [ "$(uname -m)" = x86_64 ] || {
        echo 'The release AppImage build currently supports x86_64 only.' >&2
        return 1
    }
    [ -f "$ROOT/pyproject.toml" ] || {
        echo 'AppImage builds require the repository checkout.' >&2
        return 1
    }
    [ -x "$DOUBLETAKE_DIR/bin/doubletake" ] || \
        SCREENMAGNET_DOUBLETAKE="$DOUBLETAKE_DIR" "$ROOT/packaging/linux/install-doubletake.sh"
    PYTHON="${PYTHON:-$(find_python)}" \
        "$ROOT/packaging/linux/build-appimage.sh" "$DOUBLETAKE_DIR/bin/doubletake"
    bash "$ROOT/packaging/linux/verify-appimage.sh" "$APPIMAGE_DEFAULT"
}

run_tests() {
    [ -x "$VENV/bin/python" ] || setup_source
    QT_QPA_PLATFORM=offscreen PYTHONPATH="$ROOT/app" \
        "$VENV/bin/python" "$ROOT/app/tests/ci_smoke_test.py"
    if find_appimage >/dev/null; then
        bash "$ROOT/packaging/linux/verify-appimage.sh" "$(find_appimage)"
    fi
}

usage() {
    cat <<'USAGE'
Usage: bash screenmagnet-linux.sh [command] [-- app arguments]

Commands:
  run              Prefer a nearby AppImage; otherwise prepare and run source
  run-appimage     Run the AppImage, automatically falling back without FUSE
  run-source       Prepare and run the isolated Python source environment
  setup-source     Install Python packages in the managed venv and build doubletake
  install-deps     Install native GStreamer/capture packages (uses sudo)
  setup-steamos    Create the GStreamer-enabled distrobox fallback
  build-appimage   Build and structurally verify the x86_64 AppImage
  test             Run offline Python and AppImage verification
  doctor           Report missing runtime pieces without changing the system
USAGE
}

COMMAND="${1:-run}"
[ $# -eq 0 ] || shift
RUN_ARGS=("$@")
case "$COMMAND" in
    run) run_auto ;;
    run-appimage) run_appimage ;;
    run-source) run_source ;;
    setup-source) setup_source ;;
    install-deps) install_native_deps ;;
    setup-steamos) setup_steamos ;;
    build-appimage) build_appimage ;;
    test) run_tests ;;
    doctor) doctor ;;
    help|-h|--help) usage ;;
    *) usage >&2; exit 2 ;;
esac
