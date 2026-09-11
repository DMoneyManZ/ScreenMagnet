"""Release data checks use synthetic sources and archives, never network or installers."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReleaseData(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'packaging/stage_release_data.py'
        self.assertTrue(path.is_file(), 'release-data staging implementation is missing')
        spec = importlib.util.spec_from_file_location('release_data', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, root, name, content='source'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_application_source_excludes_private_and_prebuilt_files(self):
        root = self.root / 'app'
        wanted = ['LICENSE', 'pyproject.toml', 'README.md', 'CHANGELOG.md', '.gitignore', '.github/FUNDING.yml',
                  'screenmagnet-linux.sh', 'app/screenmagnet/__init__.py',
                  'app/assets/screenmagnet.svg', 'packaging/windows/build.ps1',
                  'patches/0001.patch', 'app/tests/test_core.py', 'docs/WINDOWS-INSTALL.md']
        unwanted = ['.git/config', '.env', 'lora/training.py', 'docs/RESEARCH-FINDINGS.md',
                    'docs/superpowers/session.md', 'app/screenmagnet/__pycache__/cache.pyc',
                    'packaging/windows/vendor/doubletake.exe', 'packaging/windows/vendor/README.md',
                    'app/assets/private.key', 'packaging/logs/build.txt', 'docs/token.log',
                    'packaging/linux/build-venv/lib/site-packages/private.py',
                    'packaging/linux/AppDir/usr/share/screenmagnet/source/private.txt',
                    'packaging/linux/frozen/ScreenMagnet/private.py',
                    'packaging/windows/output/private.txt', 'packaging/linux/ScreenMagnet.spec']
        for name in wanted + unwanted:
            self.write(root, name)
        result = {p.relative_to(root).as_posix() for p in self.module.application_files(root)}
        self.assertEqual(result, set(wanted))

    def test_symlinked_source_cannot_escape_allowlist(self):
        root = self.root / 'app'
        self.write(root, 'LICENSE')
        outside = self.write(self.root, 'outside.py')
        link = root / 'app/screenmagnet/link.py'
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest('host cannot create symlinks')
        with self.assertRaises(ValueError):
            list(self.module.application_files(root))

    def test_doubletake_archive_preserves_vendor_sources_and_excludes_credentials(self):
        root = self.root / 'doubletake'
        wanted = ['LICENSE', 'README.md', 'go.mod', 'go.sum', 'cmd/doubletake/main.go',
                  'internal/airplay/credentials.go', 'internal/airplay/credentials_keyring.go',
                  'vendor/modules.txt', 'vendor/example.org/lib/lib.go',
                  'vendor/example.org/lib/LICENSE', 'vendor/example.org/lib/table.bin']
        for name in wanted + ['.git/config', 'bin/doubletake', 'credentials.json', 'private.key',
                              'vendor/example.org/lib/cache.exe', 'capture.log']:
            self.write(root, name)
        archive = self.root / 'doubletake.tar.gz'
        self.module.write_source_archive(root, self.module.doubletake_files(root), archive, 'DoubleTake')
        with tarfile.open(archive) as handle:
            self.assertEqual(set(handle.getnames()), {'DoubleTake/' + p for p in wanted})

    def test_missing_go_vendor_manifest_fails_instead_of_shipping_incomplete_source(self):
        root = self.root / 'doubletake'
        for name in ('LICENSE', 'go.mod', 'go.sum', 'main.go'):
            self.write(root, name)
        with self.assertRaises(ValueError):
            list(self.module.doubletake_files(root))

    def archive(self, members):
        path = self.root / 'input.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, content in members:
                item = tarfile.TarInfo(name)
                data = content.encode()
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        return path

    def test_notice_extraction_preserves_upstream_text_only(self):
        archive = self.archive([('pkg/LICENSES/LGPL-3.0.txt', 'LGPL text'),
                                ('pkg/src/COPYING', 'notice'), ('pkg/src/main.c', 'code')])
        target = self.root / 'notices'
        self.module.extract_notices(archive, target)
        self.assertEqual((target / 'pkg/LICENSES/LGPL-3.0.txt').read_text(), 'LGPL text')
        self.assertEqual((target / 'pkg/src/COPYING').read_text(), 'notice')
        self.assertFalse((target / 'pkg/src/main.c').exists())

    def test_unsafe_archive_is_rejected_before_any_notice_is_written(self):
        archive = self.archive([('pkg/LICENSE', 'valid'), ('../LICENSE', 'escape')])
        target = self.root / 'notices'
        with self.assertRaises(ValueError):
            self.module.extract_notices(archive, target)
        self.assertFalse(target.exists())

    def test_download_hash_mismatch_never_becomes_a_release_input(self):
        from unittest.mock import patch
        target = self.root / 'download.tar.gz'
        with patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupted')):
            with self.assertRaises(ValueError):
                self.module.download('https://example.org/source.tar.gz', target,
                                     hashlib.sha256(b'expected').hexdigest())
        self.assertFalse(target.exists())

    def test_runtime_source_version_mismatch_is_rejected(self):
        from unittest.mock import patch
        def version(name):
            return '6.11.2' if name == 'PySide6-Essentials' else 'irrelevant'
        with patch.object(self.module.importlib.metadata, 'version', side_effect=version):
            with self.assertRaisesRegex(ValueError, 'PySide6-Essentials'):
                self.module.check_package_versions()


if __name__ == '__main__':
    unittest.main()
