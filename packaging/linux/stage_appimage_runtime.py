#!/usr/bin/env python3
"""Pin the executable AppImage runtime and stage its matching source/notices.

stdout contains only the verified runtime path for appimagetool --runtime-file.
All downloads, including cached files, must match the reviewed checksums.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request


RUNTIME_COMMIT = '75849dce7cc37e4319b633df1f116ca895c71a12'
APORTS_COMMIT = '9ba44d139997adf2fc29046f578ab596d05b7fc5'
BUILD_LOG = 'https://github.com/AppImage/type2-runtime/actions/runs/28063784345/job/83083595830'
ALPINE_IMAGE = 'alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d'

# The release tag is mutable, so the binary is accepted ONLY at this digest.
# Its release metadata and --appimage-version identify RUNTIME_COMMIT.
ASSETS = {
    'runtime-x86_64': {
        'url': 'https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64',
        'sha256': '1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf',
    },
    'type2-runtime.tar.gz': {
        'url': f'https://codeload.github.com/AppImage/type2-runtime/tar.gz/{RUNTIME_COMMIT}',
        'sha256': 'b7af4960da4b90364e935a3281d04fad6560da4813c012414fa2f738291ad443',
        'notices': (f'type2-runtime-{RUNTIME_COMMIT}/LICENSE',),
    },
    'fuse-3.15.0.tar.xz': {
        'url': 'https://github.com/libfuse/libfuse/releases/download/fuse-3.15.0/fuse-3.15.0.tar.xz',
        'sha256': '70589cfd5e1cff7ccd6ac91c86c01be340b227285c5e200baa284e401eea2ca0',
        'notices': ('fuse-3.15.0/LICENSE', 'fuse-3.15.0/LGPL2.txt', 'fuse-3.15.0/GPL2.txt'),
    },
    'squashfuse-0.5.2.tar.gz': {
        'url': 'https://github.com/vasi/squashfuse/archive/0.5.2.tar.gz',
        'sha256': 'db0238c5981dabbd80ee09ae15387f390091668ca060a7bc38047912491443d3',
        'notices': ('squashfuse-0.5.2/LICENSE',),
    },
    'musl-1.2.5.tar.gz': {
        'url': 'https://musl.libc.org/releases/musl-1.2.5.tar.gz',
        'sha256': 'a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4',
        'notices': ('musl-1.2.5/COPYRIGHT',),
    },
    'zstd-1.5.6.tar.gz': {
        'url': 'https://github.com/facebook/zstd/archive/v1.5.6.tar.gz',
        'sha256': '30f35f71c1203369dc979ecde0400ffea93c27391bfd2ac5a9715d2173d92ff7',
        'notices': ('zstd-1.5.6/LICENSE', 'zstd-1.5.6/COPYING'),
    },
    'zlib-1.3.2.tar.gz': {
        'url': 'https://zlib.net/fossils/zlib-1.3.2.tar.gz',
        'sha256': 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16',
        'notices': ('zlib-1.3.2/LICENSE',),
    },
    'mimalloc-2.1.7.tar.gz': {
        'url': 'https://github.com/microsoft/mimalloc/archive/v2.1.7/mimalloc-2.1.7.tar.gz',
        'sha256': '0eed39319f139afde8515010ff59baf24de9e47ea316a315398e8027d198202d',
        'notices': ('mimalloc-2.1.7/LICENSE',),
    },
    'fortify-headers-1.1.tar.gz': {
        'url': 'https://distfiles.alpinelinux.org/distfiles/v3.21/fortify-headers-1.1.tar.gz',
        'sha256': '6ba5d860a2d2ba4c3346924b93930c34856eafe148bdbdf271ecab8065201fb6',
        'notices': ('fortify-headers-1.1/LICENSE',),
    },
    'aports.tar.gz': {
        'url': f'https://codeload.github.com/alpinelinux/aports/tar.gz/{APORTS_COMMIT}',
        'sha256': 'c69de817b34b14b252482a7f31d50f49bcb3ec4f5c8b725faa186e5501a61e3c',
    },
    'GCC-COPYING3': {
        'url': 'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-14.2.0/COPYING3',
        'sha256': '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903',
    },
    'GCC-COPYING.RUNTIME': {
        'url': 'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-14.2.0/COPYING.RUNTIME',
        'sha256': '9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74',
    },
}
ALPINE_PACKAGES = {
    'main/musl': ('1.2.5', '11', 'musl-1.2.5.tar.gz'),
    'main/zstd': ('1.5.6', '2', 'zstd-1.5.6.tar.gz'),
    'main/zlib': ('1.3.2', '0', 'zlib-1.3.2.tar.gz'),
    'community/mimalloc2': ('2.1.7', '0', 'mimalloc-2.1.7.tar.gz'),
    'main/fortify-headers': ('1.1', '5', 'fortify-headers-1.1.tar.gz'),
    'main/gcc': ('14.2.0', '4', None),
}


def file_hash(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def fetch_verified(path, asset):
    """Never replace an altered cache entry or accept an unverified download."""
    if not asset['url'].startswith('https://'):
        raise ValueError('Only HTTPS source URLs are allowed')
    if path.is_symlink():
        raise ValueError(f'Linked download cache entry: {path}')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading AppImage input: {path.name}', file=sys.stderr)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with urllib.request.urlopen(asset['url'], timeout=120) as response:
                    if not response.url.startswith('https://'):
                        raise ValueError('Download redirected away from HTTPS')
                    shutil.copyfileobj(response, temporary)
                temporary.flush()
                if file_hash(temporary_path) != asset['sha256']:
                    raise ValueError(f'AppImage input checksum mismatch: {path.name}')
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
    if file_hash(path) != asset['sha256']:
        raise ValueError(f'AppImage input checksum mismatch: {path}; remove it and retry')
    return path


def safe_name(name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError(f'Unsafe archive path: {name}')
    return relative


def copy_notices(archive_path, output, required):
    """Read regular members directly; never extract archive links or devices."""
    found = set()
    with tarfile.open(archive_path) as archive:
        for member in archive:
            relative = safe_name(member.name)
            name = relative.name.lower()
            notice = (name.startswith(('license', 'copying', 'copyright', 'notice', 'authors'))
                      or name in ('lgpl2.txt', 'gpl2.txt') or 'licenses' in relative.parts)
            if not notice and member.name not in required:
                continue
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f'Unsafe notice member: {member.name}')
            destination = output.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, destination.open('wb') as target:
                shutil.copyfileobj(source, target)
            found.add(member.name)
    missing = set(required) - found
    if missing:
        raise ValueError('Missing required original notices: ' + ', '.join(sorted(missing)))


def stage_alpine_recipes(archive_path, output, cache):
    """Preserve exact distro patches without shipping unrelated aports trees."""
    prefix = f'aports-{APORTS_COMMIT}/'
    with tarfile.open(archive_path) as archive:
        for package, (version, release, source_name) in ALPINE_PACKAGES.items():
            recipe_name = prefix + package + '/APKBUILD'
            recipe = archive.extractfile(recipe_name).read().decode()
            if (not re.search(r'^pkgver=' + re.escape(version) + r'$', recipe, re.M)
                    or not re.search(r'^pkgrel=' + re.escape(release) + r'$', recipe, re.M)):
                raise ValueError(f'Alpine recipe does not match runtime build: {package}')
            if source_name:
                expected = re.search(r'^([0-9a-f]{128})  ' + re.escape(source_name) + '$', recipe, re.M)
                if not expected or file_hash(cache / source_name, 'sha512') != expected[1]:
                    raise ValueError(f'Alpine source checksum mismatch: {source_name}')
        with tarfile.open(output, 'w:gz') as staged:
            for member in archive:
                safe_name(member.name)
                if not any(member.name.startswith(prefix + package + '/') for package in ALPINE_PACKAGES):
                    continue
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError(f'Unsafe Alpine source member: {member.name}')
                with archive.extractfile(member) as source:
                    staged.addfile(member, source)


def stage(output, cache):
    output, cache = output.resolve(), cache.resolve()
    for name, asset in ASSETS.items():
        fetch_verified(cache / name, asset)
    source_dir = output / 'source/appimage-runtime'
    license_dir = output / 'licenses/appimage-runtime'
    source_dir.mkdir(parents=True, exist_ok=True)
    license_dir.mkdir(parents=True, exist_ok=True)
    for name, asset in ASSETS.items():
        if 'notices' in asset:
            copy_notices(cache / name, license_dir, asset['notices'])
            shutil.copy2(cache / name, source_dir / name)
        elif name.startswith('GCC-'):
            shutil.copy2(cache / name, license_dir / name)
    recipes = source_dir / 'alpine-runtime-recipes.tar.gz'
    stage_alpine_recipes(cache / 'aports.tar.gz', recipes, cache)
    shutil.copy2(Path(__file__).with_name('APPIMAGE-RUNTIME.md'), source_dir / 'README.md')
    manifest = {
        'schema_version': 1, 'architecture': 'x86_64',
        'runtime_commit': RUNTIME_COMMIT, 'upstream_build_log': BUILD_LOG,
        'upstream_build_date': '2026-06-23', 'alpine_image': ALPINE_IMAGE,
        'aports_commit': APORTS_COMMIT,
        'alpine_packages': {name: version + '-r' + release
                            for name, (version, release, _) in ALPINE_PACKAGES.items()},
        'inputs': ASSETS,
        'staged_source_sha256': {path.name: file_hash(path) for path in sorted(source_dir.iterdir())},
        'coverage': 'Runtime, libfuse patch/build scripts, squashfuse, musl, zstd, zlib, mimalloc and fortify sources; '
                    'matching Alpine recipes/patches. GCC runtime license and exception notices; no GCC compiler payload.',
    }
    (output / 'appimage-runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    runtime = cache / 'runtime-x86_64'
    runtime.chmod(0o755)
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='AppDir/usr/share/screenmagnet')
    parser.add_argument('--cache', type=Path, required=True, help='Persistent verified download cache')
    args = parser.parse_args()
    try:
        print(stage(args.output, args.cache))
    except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print(f'AppImage runtime staging failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
