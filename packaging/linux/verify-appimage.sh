#!/usr/bin/env bash
# Offline structural/runtime verification for a built ScreenMagnet AppImage.
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <ScreenMagnet-x86_64.AppImage>" >&2
    exit 2
fi

ARTIFACT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
if [ ! -s "$ARTIFACT" ]; then
    echo "error: AppImage is missing or empty: $ARTIFACT" >&2
    exit 1
fi
chmod +x "$ARTIFACT"

WORK="$(mktemp -d)"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT

(
    cd "$WORK"
    "$ARTIFACT" --appimage-extract >/dev/null
)
ROOT="$WORK/squashfs-root"

test -x "$ROOT/AppRun"
test -x "$ROOT/usr/bin/ScreenMagnet"
test -x "$ROOT/usr/bin/doubletake/bin/doubletake"
test -f "$ROOT/screenmagnet.desktop"
test -f "$ROOT/screenmagnet.svg"
test -f "$ROOT/usr/share/screenmagnet/LICENSE"
test -f "$ROOT/usr/share/screenmagnet/THIRD-PARTY-NOTICES.md"
test -d "$ROOT/usr/share/screenmagnet/licenses"
python3 - "$ROOT/usr/share/screenmagnet" "$(dirname "$ARTIFACT")" <<'PY'
import hashlib,json,pathlib,sys,tarfile
payload,downloads=map(pathlib.Path,sys.argv[1:])
manifest=json.loads((payload/'source-archive.json').read_text())
assert manifest['file']=='ScreenMagnet-Linux-Corresponding-Source.tar.gz'
archive=downloads/manifest['file']
digest=hashlib.sha256()
with archive.open('rb') as stream:
    for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
assert digest.hexdigest()==manifest['sha256'], 'Source download does not match AppImage'
with tarfile.open(archive) as stream:
    names=set(stream.getnames())
assert {'source/ScreenMagnet-source.tar.gz','source/DoubleTake-patched-source.tar.gz',
        'licenses/components.json','licenses/system-libraries.json',
        'appimage-runtime-manifest.json','LICENSE'} <= names
print('Matching corresponding-source download verified')
PY
test -f "$ROOT/usr/share/metainfo/io.github.DMoneyManZ.ScreenMagnet.metainfo.xml"

if grep -Eq '@EXEC@|@WORKDIR@' "$ROOT/screenmagnet.desktop"; then
    echo "error: unresolved desktop-entry template token" >&2
    exit 1
fi
grep -Eq '^Exec=ScreenMagnet$' "$ROOT/screenmagnet.desktop"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$ROOT/screenmagnet.desktop"
fi

HELP="$($ROOT/usr/bin/doubletake/bin/doubletake --help 2>&1 || true)"
for flag in -monitor -target -hwaccel -pin -playout-floor-ms; do
    grep -q -- "$flag" <<<"$HELP" || {
        echo "error: bundled doubletake is missing $flag" >&2
        exit 1
    }
done

CHECKSUM="$ARTIFACT.sha256"
if [ -f "$CHECKSUM" ]; then
    (cd "$(dirname "$ARTIFACT")" && sha256sum --check "$(basename "$CHECKSUM")")
fi

# This path deliberately proves that FUSE is not required for the fallback.
XDG_DATA_HOME="$WORK/data" XDG_CONFIG_HOME="$WORK/config" \
    QT_QPA_PLATFORM=offscreen APPIMAGE_EXTRACT_AND_RUN=1 \
    "$ARTIFACT" --self-test

echo "AppImage verification passed: $ARTIFACT"
