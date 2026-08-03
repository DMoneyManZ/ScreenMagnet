#!/usr/bin/env bash
# Build doubletake (AirPlay sender) in a distrobox container.
#
# Why a container: the SteamOS host has NO H.264 GStreamer encoder (x264enc,
# openh264enc, vah264enc, vaapih264enc all absent) and steamos-readonly is enabled,
# so we cannot install them on the host. doubletake uses host GStreamer, so it gets
# a container that has one. /dev/dri is shared by distrobox for VAAPI hw encode.
#
# During development, streaming was hard-scoped to one TV - see docs/RESEARCH-FINDINGS.md §10.

set -uo pipefail

BOX=screenmagnet
IMAGE=quay.io/toolbx/arch-toolbox:latest
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/doubletake"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== 1/5 creating distrobox '$BOX' ==="
if podman container exists "$BOX" 2>/dev/null; then
    log "container already exists, reusing"
else
    distrobox create --name "$BOX" --image "$IMAGE" --yes || { log "FAILED create"; exit 1; }
fi

log "=== 2/5 installing toolchain + GStreamer (with H.264) ==="
distrobox enter "$BOX" -- bash -lc '
set -e
sudo pacman -Sy --noconfirm --needed \
    go git base-devel pkgconf \
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly \
    x264 libva libva-utils libva-mesa-driver \
    libx11 libxext libxfixes libxrandr 2>&1 | tail -5
' || { log "FAILED deps"; exit 1; }

log "=== 3/5 verifying an H.264 encoder now exists in the container ==="
distrobox enter "$BOX" -- bash -lc '
for e in x264enc vah264enc vaapih264enc openh264enc; do
    printf "  %-16s %s\n" "$e" "$(gst-inspect-1.0 $e >/dev/null 2>&1 && echo PRESENT || echo absent)"
done
'

log "=== 4/5 cloning doubletake ==="
if [ -d "$SRC/.git" ]; then
    log "repo present, fetching"
    git -C "$SRC" fetch --all 2>&1 | tail -3
else
    git clone https://github.com/omarroth/doubletake "$SRC" 2>&1 | tail -5 \
        || { log "FAILED clone - repo may not exist at that path"; exit 1; }
fi
log "HEAD: $(git -C "$SRC" log -1 --format='%h %ad %s' --date=short 2>/dev/null)"
log "LICENSE: $(head -1 "$SRC/LICENSE" 2>/dev/null || echo unknown)"

log "=== 5/5 building ==="
distrobox enter "$BOX" -- bash -lc "
cd '$SRC'
go build ./... 2>&1 | tail -20
ls -la"

log "=== DONE ==="
