#!/usr/bin/env python3
"""Match frozen Linux ELF files to exact runtime or Ubuntu source packages.

Run with the freezing interpreter on the SAME Ubuntu builder immediately after
PyInstaller. Requires configured deb-src repositories. apt-get only downloads
source packages; it neither installs packages nor executes source build scripts.
"""
import argparse
import ctypes
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

_spec = importlib.util.spec_from_file_location('release_data', Path(__file__).resolve().parents[1] / 'stage_release_data.py')
release_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_data)
sha256 = release_data.sha256


def is_elf(path):
    with path.open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def elf_files(root):
    root = root.resolve()
    for path in sorted(root.rglob('*')):
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise ValueError('Frozen library link escapes package: ' + str(path))
        if path.is_file() and is_elf(path):
            yield path


def runtime_index():
    index = {}
    for name in ('PySide6-Essentials', 'shiboken6', 'zeroconf', 'ifaddr'):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or []:
            if '.so' not in str(relative):
                continue
            path = Path(distribution.locate_file(relative))
            if path.is_file() and is_elf(path):
                index[sha256(path)] = {'component': name, 'path': str(relative), 'local_path': path}
    paths = list(Path(sysconfig.get_config_var('DESTSHARED')).glob('*.so'))
    paths += [Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')]
    for path in paths:
        if path.is_file() and is_elf(path):
            index[sha256(path)] = {'component': 'CPython', 'path': path.name, 'local_path': path}
    return index


def system_index():
    command = shutil.which('ldconfig') or '/sbin/ldconfig'
    output = subprocess.check_output([command, '-p'], text=True)
    index = {}
    for line in output.splitlines():
        match = re.match(r'\s*(\S+)\s+\(.*\)\s+=>\s+(\S+)', line)
        if match:
            index.setdefault(match[1], []).append(Path(match[2]))
    return index


def identify(path, runtime, system):
    digest = sha256(path)
    if digest in runtime:
        return 'runtime', runtime[digest]
    for candidate in system.get(path.name, []):
        if candidate.is_file() and sha256(candidate) == digest:
            return 'system', candidate
    raise ValueError('unmapped ELF (no byte-identical runtime or system library): ' + str(path))


def parse_package_metadata(text):
    fields = text.strip().split('\t')
    if len(fields) != 4 or not all(fields) or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', fields[2]):
        raise ValueError('Invalid or missing dpkg source-package metadata: ' + text)
    return dict(zip(('package', 'binary_version', 'source_package', 'source_version'), fields))


def owning_package(path):
    candidates = {path, path.resolve()}
    for candidate in list(candidates):
        value = str(candidate)
        if value.startswith('/usr/lib/'):
            candidates.add(Path(value.removeprefix('/usr')))
        elif value.startswith('/lib/'):
            candidates.add(Path('/usr' + value))
    for candidate in sorted(candidates):
        result = subprocess.run(['dpkg-query', '-S', str(candidate)], text=True, capture_output=True)
        if result.returncode:
            continue
        for line in result.stdout.splitlines():
            if ': ' not in line:
                continue
            package, owned = line.rsplit(': ', 1)
            if owned != str(candidate) or ',' in package or package.startswith('diversion'):
                continue
            details = subprocess.check_output(['dpkg-query', '-W', '-f',
                '${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n', package], text=True)
            return parse_package_metadata(details)
    raise ValueError('No installed dpkg package owns matching library: ' + str(path))


def collect_inventory(frozen):
    runtime, system = runtime_index(), system_index()
    libraries, packages, icu = [], {}, None
    allowed_qt = {'Core', 'DBus', 'Gui', 'Network', 'OpenGL', 'Widgets', 'Svg', 'SvgWidgets',
                  'WaylandClient', 'WlShellIntegration', 'EglFSDeviceIntegration', 'EglFsKmsSupport',
                  'XcbQpa', 'OpenGLWidgets', 'PrintSupport', 'Sql', 'Xml', 'Test', 'Concurrent'}
    for path in elf_files(frozen):
        relative = path.relative_to(frozen).as_posix()
        record = {'file': relative, 'sha256': sha256(path)}
        if relative == 'ScreenMagnet':
            record['component'] = 'ScreenMagnet/PyInstaller bootloader'
        else:
            kind, origin = identify(path, runtime, system)
            if kind == 'runtime':
                record.update(component=origin['component'], runtime_path=origin['path'])
                match = re.match(r'libQt6(\w+)\.so', path.name)
                if match and match[1] not in allowed_qt:
                    raise ValueError('Qt module needs additional corresponding source: ' + path.name)
                if path.name.startswith('libicuuc.so.'):
                    icu = origin['local_path']
            else:
                package = owning_package(origin)
                packages[package['package']] = package
                record.update(package=package['package'], system_path=str(origin))
        libraries.append(record)
    if not libraries:
        raise ValueError('Frozen directory has no ELF files')
    return libraries, packages, icu


def download_system_sources(stage, packages):
    sources = {}
    for package in packages.values():
        key = (package['source_package'], package['source_version'])
        folder = re.sub(r'[^A-Za-z0-9.+~-]', '_', '-'.join(key))
        if key not in sources:
            target = stage / 'source/system' / folder
            target.mkdir(parents=True)
            print('Downloading Ubuntu source:', '='.join(key), flush=True)
            subprocess.run(['apt-get', 'source', '--download-only', '--only-source', '='.join(key)],
                           cwd=target, check=True)
            files = [p for p in sorted(target.iterdir()) if p.is_file()]
            if not any(p.suffix == '.dsc' for p in files):
                raise ValueError('Source download produced no .dsc: ' + key[0])
            sources[key] = {'source_package': key[0], 'source_version': key[1],
                            'files': [{'file': p.relative_to(stage).as_posix(), 'sha256': sha256(p)} for p in files]}
        name = package['package'].split(':')[0]
        copyright_file = Path('/usr/share/doc') / name / 'copyright'
        if not copyright_file.is_file():
            raise ValueError('Missing installed copyright file: ' + name)
        target = stage / 'licenses/system' / package['package']
        target.mkdir(parents=True)
        shutil.copyfile(copyright_file, target / 'copyright')
        package['copyright'] = (target / 'copyright').relative_to(stage).as_posix()
        package['copyright_sha256'] = sha256(target / 'copyright')
    common = stage / 'licenses/system/common-licenses'
    common.mkdir(parents=True)
    for path in sorted(Path('/usr/share/common-licenses').iterdir()):
        if path.is_file():
            shutil.copyfile(path, common / path.name)
    return list(sources.values())


def stage_icu(stage, library):
    """Qt wheels ship ICU separately from Qt; inspect the real library version."""
    major = library.name.rsplit('.', 1)[-1]
    if not major.isdigit():
        raise ValueError('Cannot determine ICU ABI version')
    loaded = ctypes.CDLL(str(library))
    get_version = getattr(loaded, 'u_getVersion_' + major)
    get_version.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
    get_version.restype = None
    version = (ctypes.c_uint8 * 4)()
    get_version(version)
    parts = list(version)
    while len(parts) > 2 and parts[-1] == 0:
        parts.pop()
    if parts[0] != int(major):
        raise ValueError('ICU ABI and runtime version disagree')
    filename = 'icu4c-' + '_'.join(map(str, parts)) + '-src.tgz'
    tag = 'release-' + '-'.join(map(str, parts))
    url = 'https://github.com/unicode-org/icu/releases/download/' + tag + '/' + filename
    archive = stage / 'source/system/icu' / filename
    digest = release_data.download(url, archive)
    release_data.extract_notices(archive, stage / 'licenses/system/icu')
    return {'component': 'ICU', 'version': '.'.join(map(str, parts)), 'source_url': url,
            'file': archive.relative_to(stage).as_posix(), 'sha256': digest}


def stage_sources(frozen, output):
    if sys.platform != 'linux':
        raise ValueError('System source staging requires the original Ubuntu freezing host')
    release_data.check_package_versions()
    if not (output / 'licenses/components.json').is_file():
        raise ValueError('Stage the application and runtime sources first')
    manifest = json.loads((output / 'licenses/components.json').read_text())
    if manifest['packages'] != release_data.check_package_versions() or manifest['python'] != sys.version:
        raise ValueError('Core source payload differs from the active freezing environment')
    if not any(p['name'] == 'qtwayland' for p in manifest['sources']):
        raise ValueError('Regenerate core source payload with Qt Wayland sources')
    for name in ('source/system', 'licenses/system', 'licenses/system-libraries.json'):
        if (output / name).exists():
            raise ValueError('System source output already exists; use a fresh package directory')
    libraries, packages, icu = collect_inventory(frozen)
    print(f'Mapped {len(libraries)} ELF files to runtime components and {len(packages)} Ubuntu packages.', flush=True)
    with tempfile.TemporaryDirectory(prefix='screenmagnet-system-sources-', dir=output.parent) as temporary:
        stage = Path(temporary)
        sources = download_system_sources(stage, packages)
        extra = stage_icu(stage, icu) if icu else None
        document = {'libraries': libraries, 'packages': list(packages.values()), 'sources': sources,
                    'additional_runtime_sources': [extra] if extra else []}
        for name in ('source/system', 'licenses/system'):
            (stage / name).rename(output / name)
        (output / 'licenses/system-libraries.json').write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    print('System library sources and notices staged: ' + str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen', type=Path, required=True, help='PyInstaller directory containing ScreenMagnet and _internal')
    parser.add_argument('--output', type=Path, required=True, help='existing AppDir/usr/share/screenmagnet release-data directory')
    args = parser.parse_args()
    try:
        stage_sources(args.frozen.resolve(), args.output.resolve())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'System source staging failed: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
