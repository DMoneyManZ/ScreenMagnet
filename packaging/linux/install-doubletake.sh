#!/usr/bin/env bash
# Build and install doubletake, the AirPlay sender ScreenMagnet drives.
#
# It is not vendored: upstream is omarroth/doubletake (LGPL-3.0+), pinned to the
# commit our patches/ apply against. Everything lands under the app's own data
# directory -- no sudo, no system packages -- because SteamOS has a read-only
# root and that is the environment this has to work on.
set -euo pipefail

UPSTREAM="https://github.com/omarroth/doubletake.git"
COMMIT="8ccea5fb2a72765502f351595765812030efed5d"  # patches/ are cut against this
GO_MIN="1.25.0"                        # doubletake's go.mod

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/screenmagnet"
DEST="${SCREENMAGNET_DOUBLETAKE:-$DATA/doubletake}"
SRC="${XDG_CACHE_HOME:-$HOME/.cache}/screenmagnet/doubletake-src"
TOOLCHAIN="$DATA/toolchain"

say() { printf '\n== %s\n' "$*"; }

# --- Go -------------------------------------------------------------------
# Prefer a system Go that is new enough; otherwise fetch the official tarball
# into our own data dir. Never touches the system.
ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

GO=""
if command -v go >/dev/null 2>&1; then
    have="$(go env GOVERSION 2>/dev/null | sed 's/^go//')"
    if [ -n "$have" ] && ver_ge "$have" "$GO_MIN"; then
        GO="$(command -v go)"
        say "using system Go $have"
    fi
fi

if [ -z "$GO" ]; then
    if [ -x "$TOOLCHAIN/go/bin/go" ] \
       && ver_ge "$("$TOOLCHAIN/go/bin/go" env GOVERSION | sed 's/^go//')" "$GO_MIN"; then
        GO="$TOOLCHAIN/go/bin/go"
        say "using previously downloaded Go"
    else
        say "fetching Go toolchain (no system Go >= $GO_MIN)"
        gov="$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1)"
        case "$(uname -m)" in
            x86_64) arch=amd64 ;;
            aarch64|arm64) arch=arm64 ;;
            *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
        esac
        mkdir -p "$TOOLCHAIN"
        tarball="$TOOLCHAIN/${gov}.linux-${arch}.tar.gz"
        curl -fSL --progress-bar -o "$tarball" "https://go.dev/dl/${gov}.linux-${arch}.tar.gz"
        rm -rf "$TOOLCHAIN/go"
        tar -C "$TOOLCHAIN" -xzf "$tarball"
        rm -f "$tarball"
        GO="$TOOLCHAIN/go/bin/go"
        say "installed $("$GO" env GOVERSION) to $TOOLCHAIN/go"
    fi
fi

# --- source ---------------------------------------------------------------
say "fetching doubletake @ $COMMIT"
if [ -d "$SRC/.git" ]; then
    git -C "$SRC" fetch --quiet origin
else
    mkdir -p "$(dirname "$SRC")"
    git clone --quiet "$UPSTREAM" "$SRC"
fi
git -C "$SRC" checkout --quiet --force "$COMMIT"
git -C "$SRC" clean -qfd

say "applying patches/"
for p in "$REPO"/patches/*.patch; do
    git -C "$SRC" apply --whitespace=nowarn "$p"
    echo "   applied $(basename "$p")"
done

# --- build ----------------------------------------------------------------
say "building"
mkdir -p "$DEST/bin"
( cd "$SRC" && GOFLAGS=-trimpath "$GO" build -o "$DEST/bin/doubletake" ./cmd/doubletake )
if [ -d "$SRC/cmd/doubletake-ctl" ]; then
    ( cd "$SRC" && GOFLAGS=-trimpath "$GO" build -o "$DEST/bin/doubletake-ctl" ./cmd/doubletake-ctl )
fi

say "done"
echo "   $DEST/bin/doubletake"
"$DEST/bin/doubletake" -h 2>&1 | head -3 || true
