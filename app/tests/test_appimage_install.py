"""Per-user installation checks using a synthetic executable, never a real cast."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / 'packaging/linux/install-appimage.sh'
ICON = ROOT / 'app/assets/screenmagnet.svg'


@unittest.skipUnless(sys.platform.startswith("linux"), "AppImage desktop installer requires Linux")
class AppImageInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='screenmagnet installer ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.download = self.root / 'download folder'
        self.download.mkdir()
        self.data = self.root / 'user data'
        self.home = self.root / 'home folder'
        self.home.mkdir()
        self.config = self.root / 'user config'
        self.config.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.data),
                        XDG_CONFIG_HOME=str(self.config),
                        SCREENMAGNET_TEST_RECORD=str(self.root / 'app arguments'))
        self.appimage = self.download / 'ScreenMagnet-x86_64.AppImage'
        self.appimage.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$SCREENMAGNET_TEST_RECORD"\n')
        self.appimage.chmod(0o644)
        self.write_checksum()
        shutil.copy2(ICON, self.download / 'screenmagnet.svg')
        self.installed = self.data / 'screenmagnet/ScreenMagnet-x86_64.AppImage'
        self.wrapper = self.data / 'screenmagnet/screenmagnet'
        self.desktop = self.data / 'applications/screenmagnet.desktop'
        self.icon = self.data / 'icons/hicolor/scalable/apps/screenmagnet.svg'

    def write_checksum(self, digest=None):
        digest = digest or hashlib.sha256(self.appimage.read_bytes()).hexdigest()
        Path(str(self.appimage) + '.sha256').write_text(f'{digest}  {self.appimage.name}\n')

    def run_installer(self, *args, script=INSTALLER, success=True):
        result = subprocess.run(['bash', str(script), *map(str, args)], env=self.env,
                                cwd=self.home, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_install_spaces_and_wrapper_arguments_without_install_launch(self):
        self.run_installer(self.appimage)
        self.assertEqual(self.installed.read_bytes(), self.appimage.read_bytes())
        self.assertTrue(os.access(self.installed, os.X_OK))
        self.assertEqual(self.icon.read_bytes(), ICON.read_bytes())
        self.assertIn(f'Exec="{self.wrapper}"', self.desktop.read_text())
        self.assertIn('Icon=screenmagnet', self.desktop.read_text())
        self.assertFalse((self.root / 'app arguments').exists(), 'Installation launched the application')
        result = subprocess.run([str(self.wrapper), '--self-test', 'two words'], env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / 'app arguments').read_text().splitlines(),
                         ['--appimage-extract-and-run', '--self-test', 'two words'])

    def test_default_appimage_beside_downloaded_script(self):
        local_script = self.download / 'install-appimage.sh'
        shutil.copy2(INSTALLER, local_script)
        self.run_installer(script=local_script)
        self.assertTrue(self.installed.exists())

    def test_bad_checksum_preserves_existing_installation(self):
        self.run_installer(self.appimage)
        before = {p: p.read_bytes() for p in [self.installed, self.wrapper, self.desktop, self.icon]}
        self.appimage.write_text('#!/bin/sh\nexit 42\n')
        result = self.run_installer(self.appimage, success=False)
        self.assertIn('checksum', (result.stdout + result.stderr).lower())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_missing_checksum_rejected_before_installation(self):
        Path(str(self.appimage) + '.sha256').unlink()
        self.run_installer(self.appimage, success=False)
        self.assertFalse(self.installed.exists())

    def test_checksum_must_name_the_selected_appimage(self):
        digest = hashlib.sha256(self.appimage.read_bytes()).hexdigest()
        Path(str(self.appimage) + '.sha256').write_text(f'{digest}  unrelated.AppImage\n')
        self.run_installer(self.appimage, success=False)
        self.assertFalse(self.installed.exists())

    def test_release_checksum_manifest_is_supported(self):
        Path(str(self.appimage) + '.sha256').rename(self.download / 'SHA256SUMS')
        self.run_installer(self.appimage)
        self.assertTrue(self.installed.exists())

    def test_uninstall_retains_pairing_and_unrelated_files(self):
        self.run_installer(self.appimage)
        pairing = self.config / 'screenmagnet/pairing.json'
        pairing.parent.mkdir(); pairing.write_text('saved pairing')
        unrelated = self.data / 'screenmagnet/presets/custom.json'
        unrelated.parent.mkdir(); unrelated.write_text('personal data')
        self.run_installer('--uninstall')
        for path in [self.installed, self.wrapper, self.desktop, self.icon]:
            self.assertFalse(path.exists(), path)
        self.assertEqual(pairing.read_text(), 'saved pairing')
        self.assertEqual(unrelated.read_text(), 'personal data')
        self.run_installer('--uninstall')

    def test_missing_icon_does_not_run_appimage_to_extract_it(self):
        # The distributed helper must work independently of the source checkout.
        local_script = self.download / 'install-appimage.sh'
        shutil.copy2(INSTALLER, local_script)
        (self.download / 'screenmagnet.svg').unlink()
        result = self.run_installer(script=local_script, success=False)
        self.assertIn('screenmagnet.svg', result.stdout + result.stderr)
        self.assertFalse(self.installed.exists())
        self.assertFalse((self.root / 'app arguments').exists())


if __name__ == '__main__':
    unittest.main()
