"""Windows installation contracts, also checked without a Windows desktop."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from screenmagnet import windows_runtime as runtime


class InstalledRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Windows TEMP can use an 8.3 alias (RUNNER~1); use the same canonical
        # spelling as the frozen executable resolver for every path fixture.
        self.root = Path(self.temporary.name).resolve()

    def test_frozen_sender_is_found_beside_exe_without_registry_environment(self):
        with patch.object(runtime, 'IS_WINDOWS', True), patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', str(self.root / 'Program Files/ScreenMagnet/ScreenMagnet.exe')), \
                patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime.sender_directory(), self.root / 'Program Files/ScreenMagnet/doubletake')

    def test_explicit_sender_override_is_preserved(self):
        with patch.dict(os.environ, {'SCREENMAGNET_DOUBLETAKE': str(self.root / 'custom')}):
            self.assertEqual(runtime.sender_directory(), self.root / 'custom')

    def test_sender_state_is_writable_user_data_not_program_files(self):
        with patch.object(runtime, 'IS_WINDOWS', True), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'Local')}):
            directory = runtime.sender_working_directory()
            self.assertEqual(directory, self.root / 'Local/ScreenMagnet/sender-state')
            self.assertTrue(directory.is_dir())

    def test_windows_sender_receives_explicit_private_credentials_path(self):
        from screenmagnet import caster
        with patch.object(caster, 'IS_WINDOWS', True), patch.object(runtime, 'IS_WINDOWS', True), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'Local')}):
            program, arguments = caster._sender_argv(['-target', '192.0.2.24'])
        self.assertEqual(arguments, ['-target', '192.0.2.24', '-creds',
                                   str(self.root / 'Local/ScreenMagnet/sender-state/credentials.json')])

    def test_standard_gstreamer_install_precedes_stale_generic_environment(self):
        standard = self.root / 'Programs/gstreamer/1.0/msvc_x86_64/bin'
        stale = self.root / 'stale-runtime/bin'
        explicit = self.root / 'chosen-runtime/bin'
        for directory in (standard, stale, explicit):
            directory.mkdir(parents=True)
            for name in ('gst-launch-1.0.exe', 'gst-inspect-1.0.exe'):
                (directory / name).touch()
        with patch.object(runtime, 'IS_WINDOWS', True), patch.dict(os.environ, {
                'ProgramFiles': str(self.root / 'Programs'), 'SystemDrive': str(self.root),
                'GSTREAMER_ROOT_X86_64': str(stale.parent), 'PATH': '',
        }, clear=True):
            self.assertEqual(runtime.gstreamer_bin(), standard)
            with patch.dict(os.environ, {'SCREENMAGNET_GSTREAMER': str(explicit.parent)}):
                self.assertEqual(runtime.gstreamer_bin(), explicit)

    def test_gstreamer_is_discovered_without_inherited_path(self):
        bin_dir = self.root / 'Programs/gstreamer/1.0/msvc_x86_64/bin'
        bin_dir.mkdir(parents=True)
        for name in ('gst-launch-1.0.exe', 'gst-inspect-1.0.exe'):
            (bin_dir / name).touch()
        with patch.object(runtime, 'IS_WINDOWS', True), \
                patch.dict(os.environ, {'ProgramFiles': str(self.root / 'Programs'), 'PATH': ''}, clear=True):
            environment = runtime.child_environment()
            self.assertEqual(Path(environment['PATH'].split(os.pathsep)[0]), bin_dir)
            self.assertEqual(os.environ['PATH'], '')

    def test_gstreamer_override_requires_both_runtime_tools(self):
        directory = self.root / 'gst/bin'
        directory.mkdir(parents=True)
        (directory / 'gst-launch-1.0.exe').touch()
        with patch.object(runtime, 'IS_WINDOWS', True), \
                patch.dict(os.environ, {'SCREENMAGNET_GSTREAMER': str(directory.parent),
                                        'SystemDrive': str(self.root), 'PATH': ''}, clear=True):
            self.assertIsNone(runtime.gstreamer_bin())
            (directory / 'gst-inspect-1.0.exe').touch()
            self.assertEqual(runtime.gstreamer_bin(), directory)

    def test_failed_sender_start_is_reported_and_session_cleared(self):
        from PySide6.QtWidgets import QApplication
        from screenmagnet import caster
        app = QApplication.instance() or QApplication([])
        sender = caster.Caster()
        failures = []
        sender.failed.connect(failures.append)
        with patch.object(caster, 'preflight', return_value=[]), \
                patch.object(caster, '_sender_argv', return_value=(str(self.root / 'missing.exe'), [])), \
                patch.object(caster, '_runs_natively', return_value=True), \
                patch.object(runtime, 'sender_working_directory', return_value=self.root):
            sender.start('192.0.2.24')
            if sender._proc is not None:
                sender._proc.waitForStarted(1000)
            app.processEvents()
        self.assertTrue(failures, 'A failed CreateProcess/exec must reach the UI')
        self.assertFalse(sender.active)
        self.assertIsNone(sender._proc)

    def test_self_test_writes_failure_report_and_returns_nonzero(self):
        from screenmagnet import __main__ as entry
        report = self.root / 'self-test.json'
        with patch.object(entry, '_self_test_checks', side_effect=RuntimeError('missing runtime')), \
                patch.object(sys, 'stdout', None):
            self.assertEqual(entry._run_self_test(report), 1)
        import json
        result = json.loads(report.read_text())
        self.assertFalse(result['passed'])
        self.assertIn('missing runtime', result['error'])

    def test_unwritable_self_test_report_is_a_failure(self):
        from screenmagnet import __main__ as entry
        with patch.object(entry, '_self_test_checks', return_value={'synthetic_video_encode': True}), \
                patch.object(sys, 'stdout', None):
            self.assertEqual(entry._run_self_test(self.root), 1)


if __name__ == '__main__':
    unittest.main()
