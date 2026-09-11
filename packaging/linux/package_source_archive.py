#!/usr/bin/env python3
"""Create the matching Linux source download before assembling the AppImage."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

NAME = 'ScreenMagnet-Linux-Corresponding-Source.tar.gz'
INPUTS = ('source', 'licenses', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'appimage-runtime-manifest.json')


def package(payload, dist):
    for name in INPUTS:
        if not (payload / name).exists():
            raise ValueError('Missing source archive input: ' + name)
    dist.mkdir(parents=True, exist_ok=True)
    archive = dist / NAME
    with tarfile.open(archive, 'w:gz', compresslevel=1) as stream:
        for name in INPUTS:
            stream.add(payload / name, arcname=name)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (dist / (NAME + '.sha256')).write_text(f'{digest}  {NAME}\n', encoding='ascii')
    (payload / 'source-archive.json').write_text(json.dumps({
        'file': NAME, 'sha256': digest,
        'download': 'https://github.com/DMoneyManZ/ScreenMagnet/releases',
        'instructions': 'Download this source archive from the SAME release as this AppImage. '
                        'It contains application and dependency sources, build scripts, and original notices. '
                        'Preserve both downloads when redistributing this release.'
    }, indent=2) + '\n', encoding='utf-8')
    # Only this generated source payload is removed. Notices remain in the app.
    shutil.rmtree(payload / 'source')
    print('Created corresponding source download:', archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    args = parser.parse_args()
    package(args.payload.resolve(), args.dist.resolve())
