#!/usr/bin/env python3
"""Stage source archives and original notices for a clean ScreenMagnet build.

Run in the same Python environment used by PyInstaller, after building the
patched DoubleTake checkout with `go mod vendor`. No installer binaries are
downloaded or redistributed here. Network access is to upstream source hosts.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
QT_VERSION = '6.11.1'
PINNED = {'PySide6-Essentials': QT_VERSION, 'shiboken6': QT_VERSION,
          'zeroconf': '0.150.0', 'PyInstaller': '6.22.2'}
SKIP_DIRS = {'.git', '.venv', '__pycache__', 'build', 'dist', 'bin', 'logs',
             'credentials', 'secrets', 'lora', 'superpowers', 'build-venv',
             'frozen', 'appdir', 'output', 'prereqs', 'runtime-cache'}
SKIP_SUFFIXES = {'.exe', '.dll', '.so', '.dylib', '.o', '.a', '.pyc', '.pyd',
                 '.log', '.key', '.pem', '.zip', '.7z', '.msi', '.msix'}


def excluded(relative):
    return (any(p.lower() in SKIP_DIRS or p.startswith('.') or p.endswith('.egg-info') for p in relative.parts)
            or relative.suffix.lower() in SKIP_SUFFIXES
            or relative.name.lower().startswith(('credentials', 'secrets', 'token.')))


def selected_tree(root, folder, suffixes=None):
    """Walk allowed roots without following linked files or directories."""
    start = root / folder
    if start.is_symlink():
        raise ValueError('Linked source directory: ' + str(start))
    if not start.is_dir():
        return
    for current, dirs, files in os.walk(start, followlinks=False):
        current = Path(current)
        for name in list(dirs):
            path = current / name
            if excluded(path.relative_to(root)):
                dirs.remove(name)
            elif path.is_symlink():
                raise ValueError('Linked source directory: ' + str(path))
        for name in sorted(files):
            path = current / name
            relative = path.relative_to(root)
            if excluded(relative) or (suffixes is not None and path.suffix.lower() not in suffixes):
                continue
            if path.is_symlink():
                raise ValueError('Linked source file: ' + str(path))
            yield path


def application_files(root):
    root = Path(root)
    for name in ('LICENSE', 'README.md', 'CHANGELOG.md', '.gitignore', '.github/FUNDING.yml',
                 'pyproject.toml', 'screenmagnet-linux.sh', 'app/run.sh', 'app/run.bat',
                 'app/run-settings.bat', 'app/screenmagnet.desktop', 'spike/latency-clock.py'):
        path = root / name
        if path.is_symlink():
            raise ValueError('Linked application source: ' + name)
        if path.is_file():
            yield path
    for folder, suffixes in (
        ('app/screenmagnet', {'.py'}), ('app/assets', {'.svg', '.png', '.ico'}),
        ('app/tests', {'.py'}), ('patches', {'.patch'}),
        ('packaging', {'.py', '.ps1', '.sh', '.iss', '.txt', '.desktop', '.xml', '.md'}),
        ('docs', {'.md', '.png', '.svg'}),
    ):
        for path in selected_tree(root, folder, suffixes):
            relative = path.relative_to(root)
            if folder == 'packaging' and 'vendor' in relative.parts:
                continue
            if folder == 'docs' and 'research' in path.name.lower():
                continue
            yield path
    # Workflow files are build inputs; no other hidden configuration is copied.
    for path in sorted((root / '.github/workflows').glob('*.yml')):
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise ValueError('Linked workflow input')
        yield path


def is_notice(path):
    return (any(p.lower() == 'licenses' for p in path.parts)
            or path.name.lower().startswith(('license', 'copying', 'notice', 'copyright', 'patents'))
            or path.name.lower() == 'qt_attribution.json')


def doubletake_files(root):
    root = Path(root)
    for name in ('LICENSE', 'go.mod', 'go.sum', 'vendor/modules.txt'):
        if not (root / name).is_file():
            raise ValueError('Incomplete DoubleTake source; missing ' + name + '. Run go mod vendor first.')
    for path in selected_tree(root, '.'):
        relative = path.relative_to(root)
        # Go vendor contains source, headers and go:embed data, so preserve its
        # non-executable resources, not just *.go. The checkout's root stays narrow.
        if ('vendor' == relative.parts[0] or path.suffix.lower() in {'.go', '.c', '.h', '.s', '.cc', '.cpp', '.inc', '.asm'}
                or path.name in ('go.mod', 'go.sum', 'Makefile') or is_notice(relative)
                or (path.suffix.lower() == '.md' and (len(relative.parts) == 1 or relative.parts[0] == 'docs'))):
            yield path


def write_source_archive(root, files, destination, prefix):
    files = sorted(set(files))
    if not files:
        raise ValueError('Cannot create an empty source archive')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, 'w:gz') as archive:
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ValueError('Source input changed or is linked: ' + str(path))
            name = prefix + '/' + path.relative_to(root).as_posix()
            info = archive.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with path.open('rb') as source:
                archive.addfile(info, source)


def safe_member(name):
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in name
            or any(':' in p for p in path.parts)):
        raise ValueError('Unsafe source archive member: ' + name)
    return path


def extract_notices(source, target):
    """Preflight every path; only write regular notice files, never links."""
    notices = []
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for item in archive.infolist():
                path = safe_member(item.filename)
                if is_notice(path) and not item.is_dir():
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Linked notice in source archive')
                    notices.append((path, archive.read(item)))
    else:
        with tarfile.open(source, 'r:*') as archive:
            for item in archive.getmembers():
                path = safe_member(item.name)
                if is_notice(path) and not item.isdir():
                    if not item.isfile():
                        raise ValueError('Non-regular notice in source archive')
                    notices.append((path, archive.extractfile(item).read()))
    if not notices:
        raise ValueError('No original license notices in ' + source.name)
    target.mkdir(parents=True, exist_ok=False)
    for path, data in notices:
        destination = target.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, destination, expected_hash=None):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('Dependency sources must use HTTPS')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open('xb') as out:
            shutil.copyfileobj(response, out)
        digest = sha256(partial)
        if not partial.stat().st_size or (expected_hash and digest != expected_hash.lower()):
            raise ValueError('Dependency source is empty or has an incorrect SHA-256: ' + url)
        partial.replace(destination)
        return digest
    finally:
        partial.unlink(missing_ok=True)


def check_package_versions():
    versions = {}
    for name, expected in PINNED.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError('Missing build dependency: ' + name) from None
        if actual != expected:
            raise ValueError(f'{name}=={expected} required; found {actual}')
        versions[name] = actual
    # ifaddr is a runtime dependency of zeroconf. Include the exact installed
    # release, even when a build requirements file has not pinned it separately.
    versions['ifaddr'] = importlib.metadata.version('ifaddr')
    return versions


def stage_dependencies(stage, versions):
    records = []
    for module in ('qtbase', 'qtsvg', 'qtimageformats', 'qtwayland', 'pyside-setup'):
        filename = f'{module}-everywhere-src-{QT_VERSION}.tar.xz'
        base = (f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{QT_VERSION}-src/'
                if module == 'pyside-setup' else
                f'https://download.qt.io/official_releases/qt/6.11/{QT_VERSION}/submodules/')
        source = stage / 'source/dependencies' / filename
        digest = download(base + filename, source)
        extract_notices(source, stage / 'licenses' / module)
        records.append({'name': module, 'version': QT_VERSION, 'source_url': base + filename,
                        'archive': source.relative_to(stage).as_posix(), 'sha256': digest})
    for name in ('zeroconf', 'ifaddr'):
        version = versions[name]
        url = f'https://pypi.org/pypi/{name}/{version}/json'
        with urllib.request.urlopen(url, timeout=60) as response:
            metadata = json.load(response)
        sdists = [entry for entry in metadata['urls'] if entry['packagetype'] == 'sdist']
        if len(sdists) != 1:
            raise ValueError('Expected one exact source distribution for ' + name)
        entry = sdists[0]
        filename = safe_member(entry['filename'])
        if len(filename.parts) != 1 or urllib.parse.urlsplit(entry['url']).hostname != 'files.pythonhosted.org':
            raise ValueError('Unexpected PyPI source location')
        source = stage / 'source/dependencies' / filename.name
        digest = download(entry['url'], source, entry['digests']['sha256'])
        extract_notices(source, stage / 'licenses' / name)
        records.append({'name': name, 'version': version, 'source_url': entry['url'],
                        'archive': source.relative_to(stage).as_posix(), 'sha256': digest})
    python_version = '.'.join(map(str, sys.version_info[:3]))
    for remote, local in [('LICENSE', 'LICENSE.txt'), ('Doc/license.rst', 'THIRD-PARTY-LICENSES.rst')]:
        download(f'https://raw.githubusercontent.com/python/cpython/v{python_version}/{remote}',
                 stage / 'licenses/python' / local)
    download('https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.2/COPYING.txt',
             stage / 'licenses/pyinstaller/COPYING.txt')
    return records


def stage_release(doubletake, output):
    if sys.version_info[:2] != (3, 13):
        raise ValueError('Stage release data with the Python 3.13 build interpreter')
    versions = check_package_versions()
    doubletake = doubletake.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError('Output must not exist; remove only the previous build staging directory first')
    app_files = list(application_files(ROOT))
    go_files = list(doubletake_files(doubletake))
    for name in ('LICENSE', 'README.md', 'pyproject.toml', 'packaging/THIRD-PARTY-NOTICES.md'):
        if ROOT / name not in app_files:
            raise ValueError('Missing required application release input: ' + name)
    go_version, goroot = subprocess.check_output(['go', 'env', 'GOVERSION', 'GOROOT'], text=True).strip().splitlines()
    go_license = Path(goroot) / 'LICENSE'
    if not go_license.is_file():
        raise ValueError('Go toolchain license is missing')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='screenmagnet-release-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'data'
        stage.mkdir()
        app_archive = stage / 'source/ScreenMagnet-source.tar.gz'
        go_archive = stage / 'source/DoubleTake-patched-source.tar.gz'
        write_source_archive(ROOT, app_files, app_archive, 'ScreenMagnet')
        write_source_archive(doubletake, go_files, go_archive, 'DoubleTake')
        extract_notices(app_archive, stage / 'licenses/screenmagnet')
        extract_notices(go_archive, stage / 'licenses/doubletake')
        (stage / 'licenses/go').mkdir()
        shutil.copy2(go_license, stage / 'licenses/go/LICENSE')
        sources = stage_dependencies(stage, versions)
        with (ROOT / 'pyproject.toml').open('rb') as handle:
            app_version = tomllib.load(handle)['project']['version']
        for name, archive in [('ScreenMagnet', app_archive), ('DoubleTake-patched', go_archive)]:
            sources.append({'name': name, 'archive': archive.relative_to(stage).as_posix(), 'sha256': sha256(archive)})
        manifest = {'screenmagnet': app_version, 'python': sys.version,
                    'go': go_version, 'packages': versions, 'sources': sources,
                    'go_vendor_modules': (doubletake / 'vendor/modules.txt').read_text(encoding='utf-8'),
                    'external_prerequisites_not_bundled': ['GStreamer', 'Microsoft Visual C++ Redistributable']}
        (stage / 'licenses/components.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        shutil.copy2(ROOT / 'packaging/THIRD-PARTY-NOTICES.md', stage / 'THIRD-PARTY-NOTICES.md')
        stage.rename(output)
    print('Staged corresponding sources and notices: ' + str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doubletake-source', type=Path, required=True, help='patched checkout after go mod vendor')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/release-data')
    args = parser.parse_args()
    try:
        stage_release(args.doubletake_source, args.output.absolute())
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile,
            importlib.metadata.PackageNotFoundError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'Release data staging failed: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
