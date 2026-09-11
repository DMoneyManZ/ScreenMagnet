"""Fail-closed handling of the executable runtime and matching source inputs."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[2] / 'packaging/linux/stage_appimage_runtime.py'


class AppImageRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELPER.is_file(), 'Pinned runtime staging helper is missing')
        spec = importlib.util.spec_from_file_location('runtime_staging', HELPER)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def archive(self, entries):
        path = self.root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_altered_cached_runtime_is_rejected_without_download(self):
        cached = self.root / 'runtime'
        cached.write_bytes(b'altered')
        asset = {'url': 'https://example.invalid/runtime',
                 'sha256': hashlib.sha256(b'expected').hexdigest()}
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.helper.fetch_verified(cached, asset)

    def test_verified_cache_works_without_network(self):
        cached = self.root / 'runtime'
        cached.write_bytes(b'expected')
        asset = {'url': 'https://example.invalid/runtime',
                 'sha256': hashlib.sha256(b'expected').hexdigest()}
        self.assertEqual(self.helper.fetch_verified(cached, asset), cached)

    def test_original_lgpl_terms_are_copied_alongside_license_pointer(self):
        archive = self.archive({'fuse/LICENSE': b'see LGPL2.txt', 'fuse/LGPL2.txt': b'original terms'})
        destination = self.root / 'notices'
        self.helper.copy_notices(archive, destination, ('fuse/LICENSE', 'fuse/LGPL2.txt'))
        self.assertEqual((destination / 'fuse/LGPL2.txt').read_bytes(), b'original terms')

    def test_missing_required_notice_fails_closed(self):
        archive = self.archive({'fuse/LICENSE': b'see LGPL2.txt'})
        with self.assertRaisesRegex(ValueError, 'Missing.*LGPL2'):
            self.helper.copy_notices(archive, self.root / 'notices', ('fuse/LGPL2.txt',))

    def test_archive_traversal_is_rejected(self):
        archive = self.archive({'../LICENSE': b'escape'})
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.helper.copy_notices(archive, self.root / 'notices', ())
        self.assertFalse((self.root / 'LICENSE').exists())

    def test_alpine_recipe_must_match_the_binarys_build_version(self):
        prefix = 'aports-' + self.helper.APORTS_COMMIT + '/'
        archive = self.archive({prefix + 'main/musl/APKBUILD': b'pkgver=1.2.5\npkgrel=10\n'})
        with self.assertRaisesRegex(ValueError, 'does not match runtime build'):
            self.helper.stage_alpine_recipes(archive, self.root / 'recipes.tar.gz', self.root)


if __name__ == '__main__':
    unittest.main()
