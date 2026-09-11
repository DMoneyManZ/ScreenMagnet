"""Host tools must not load PyInstaller's bundled Linux libraries."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenmagnet import windows_runtime as runtime


class LinuxEnvironmentTests(unittest.TestCase):
    def child(self, environment, frozen=True):
        with patch.object(sys, 'platform', 'linux'), patch.object(sys, 'frozen', frozen, create=True), \
                patch.object(runtime, 'IS_WINDOWS', False), patch.dict(os.environ, environment, clear=True):
            result = runtime.child_environment()
            self.assertEqual(dict(os.environ), environment, 'The running Qt process environment must not change')
            return result

    def test_frozen_child_restores_original_library_path(self):
        result = self.child({'LD_LIBRARY_PATH': '/bundle/_internal:/caller/libs',
                             'LD_LIBRARY_PATH_ORIG': '/caller/libs', 'PATH': '/usr/bin'})
        self.assertEqual(result['LD_LIBRARY_PATH'], '/caller/libs')

    def test_frozen_child_removes_injected_path_when_original_was_unset(self):
        self.assertNotIn('LD_LIBRARY_PATH', self.child({'LD_LIBRARY_PATH': '/bundle/_internal'}))

    def test_unfrozen_source_launch_retains_callers_library_path(self):
        self.assertEqual(self.child({'LD_LIBRARY_PATH': '/caller/libs'}, frozen=False)['LD_LIBRARY_PATH'], '/caller/libs')


@unittest.skipUnless(sys.platform.startswith('linux'), 'Executable Linux tool fixtures')
class LinuxHostToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='screenmagnet-linux-tools-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.environment = {'PATH': str(self.root) + os.pathsep + os.defpath,
                            'LD_LIBRARY_PATH': '/bundle/_internal:/caller/libs',
                            'LD_LIBRARY_PATH_ORIG': '/caller/libs'}

    def tool(self, name, body='exit 0'):
        path = self.root / name
        path.write_text('#!/bin/sh\n[ "$LD_LIBRARY_PATH" = /caller/libs ] || exit 19\n' + body + '\n')
        path.chmod(0o755)

    def test_encoder_probe_uses_host_libraries(self):
        from screenmagnet import caster
        self.tool('gst-inspect-1.0')
        caster._has_native_encoder.cache_clear()
        self.addCleanup(caster._has_native_encoder.cache_clear)
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, self.environment, clear=True):
            self.assertTrue(caster._has_native_encoder())

    def test_xrandr_fallback_uses_host_libraries(self):
        from screenmagnet import monitors
        self.tool('xrandr', "printf 'HDMI-1 connected primary 1920x1080+0+0 (normal)\\n'")
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, self.environment, clear=True):
            result = monitors._from_xrandr()
        self.assertEqual([(item.name, item.width) for item in result], [('HDMI-1', 1920)])

    def test_explicit_capture_check_fails_when_gstreamer_is_missing(self):
        from screenmagnet import __main__ as entry
        with patch.dict(os.environ, {'PATH': str(self.root)}, clear=True):
            # Exercise the specific optional capture checker without a receiver.
            with self.assertRaisesRegex(RuntimeError, 'GStreamer'):
                entry._check_linux_capture_runtime({'PATH': str(self.root)})

    def test_ordinary_self_test_does_not_require_linux_gstreamer(self):
        from screenmagnet import __main__ as entry, caster
        binary = self.root / 'sender'
        binary.write_text("#!/bin/sh\nprintf '%s\\n' '-monitor -target -hwaccel -pin -playout-floor-ms'\n")
        binary.chmod(0o755)
        with patch.object(caster, 'BINARY', binary), patch.dict(os.environ, {'PATH': ''}):
            report = entry._self_test_checks(require_capture_runtime=False)
        self.assertTrue(report['sender_help_checked'])
        self.assertFalse(report['capture_runtime_checked'])

    def test_synthetic_check_uses_clean_environment_and_reports_no_real_capture(self):
        from screenmagnet import __main__ as entry
        self.tool('gst-inspect-1.0')
        self.tool('gst-launch-1.0', '[ "$2" = videotestsrc ] || exit 20')
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, self.environment, clear=True):
            report = entry._check_linux_capture_runtime(runtime.child_environment())
        self.assertTrue(report['synthetic_video_encode'])
        self.assertFalse(report['real_capture_tested'])
        self.assertFalse(report['airplay_receiver_tested'])


if __name__ == '__main__':
    unittest.main()
