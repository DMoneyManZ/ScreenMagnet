"""Source provenance checks do not run apt or require a Linux package build."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SystemSources(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'packaging/linux/stage_system_sources.py'
        self.assertTrue(path.is_file(), 'system-source staging helper is missing')
        spec = importlib.util.spec_from_file_location('system_sources', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_system_mapping_requires_identical_bytes_not_only_soname(self):
        bundled = self.root / 'bundled/libexample.so.1'
        installed = self.root / 'installed/libexample.so.1'
        bundled.parent.mkdir(); installed.parent.mkdir()
        bundled.write_bytes(b'\x7fELFone'); installed.write_bytes(b'\x7fELFtwo')
        with self.assertRaisesRegex(ValueError, 'unmapped'):
            self.module.identify(bundled, {}, {bundled.name: [installed]})
        installed.write_bytes(bundled.read_bytes())
        kind, matched = self.module.identify(bundled, {}, {bundled.name: [installed]})
        self.assertEqual(kind, 'system')
        self.assertEqual(matched, installed)

    def test_known_wheel_binary_is_matched_even_when_frozen_path_changes(self):
        bundled = self.root / 'libicuuc.so.73'; bundled.write_bytes(b'\x7fELFwheel')
        index = {self.module.sha256(bundled): {'component': 'PySide6-Essentials', 'path': 'PySide6/Qt/lib/libicuuc.so.73'}}
        kind, entry = self.module.identify(bundled, index, {})
        self.assertEqual(kind, 'runtime')
        self.assertEqual(entry['component'], 'PySide6-Essentials')

    def test_package_metadata_keeps_source_version_distinct_from_binary_version(self):
        parsed = self.module.parse_package_metadata('libthing:amd64\t2.0-3+b1\tthing\t2.0-3\n')
        self.assertEqual(parsed, {'package': 'libthing:amd64', 'binary_version': '2.0-3+b1',
                                  'source_package': 'thing', 'source_version': '2.0-3'})

    def test_missing_or_invalid_source_metadata_fails_closed(self):
        for line in ('pkg\t1.0\t\t\n', 'pkg\t1.0\t../outside\t1.0\n'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.module.parse_package_metadata(line)

    def test_elf_inventory_ignores_resources_and_rejects_external_links(self):
        root = self.root / 'frozen'; root.mkdir()
        (root / 'code.so').write_bytes(b'\x7fELFbinary')
        (root / 'icon.svg').write_text('image')
        self.assertEqual(list(self.module.elf_files(root)), [root / 'code.so'])
        external = self.root / 'external.so'; external.write_bytes(b'\x7fELFsecret')
        try:
            (root / 'linked.so').symlink_to(external)
        except OSError:
            self.skipTest('host cannot create symlinks')
        with self.assertRaises(ValueError):
            list(self.module.elf_files(root))


if __name__ == '__main__':
    unittest.main()
