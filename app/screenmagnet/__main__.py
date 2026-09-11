"""Entry point. Run via ../run.sh so the venv is used."""

from __future__ import annotations

import signal
import subprocess
import sys
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import __version__, startup, updater
from .settings_window import APP_NAME, SettingsWindow

# ScreenMagnetTray is imported lazily, inside main()'s tray-launch branch --
# tray.py pulls in caster.py's GStreamer/discovery stack, which the
# --settings path is meant to avoid dragging in at all, not just avoid
# *constructing*. Importing it at module level here would defeat that
# regardless of which branch actually runs.


def _run_settings_only(argv: list[str]) -> int:
    """`--settings`: show just the settings/about dialog, standalone, and
    exit once it's closed -- no tray icon, no discovery/scan.

    Deliberately imports only settings_window/startup/updater, never
    tray.py: tray.py pulls in caster.py's GStreamer/discovery stack, which
    is exactly what settings_window.py's own docstring says this lightweight
    launch path is meant to avoid dragging in.
    """
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    win = SettingsWindow()
    # Keep worker references alive while their threads run (nothing else
    # in this function holds one) -- see spawn() below.
    workers: list[updater.CallWorker] = []

    try:
        win.set_launch_at_startup(startup.is_enabled())
    except RuntimeError:
        pass  # non-Windows: leave the checkbox at its unchecked default

    def on_startup_toggled(enabled: bool) -> None:
        try:
            (startup.enable if enabled else startup.disable)()
        except RuntimeError as exc:  # non-Windows only, per startup.py
            win.set_update_result(str(exc), success=False)
            win.set_launch_at_startup(not enabled)

    win.startup_checkbox.toggled.connect(on_startup_toggled)

    def spawn(fn, on_done) -> None:
        worker = updater.CallWorker(fn)
        worker.done.connect(on_done)
        worker.finished.connect(lambda: workers.remove(worker) if worker in workers else None)
        worker.finished.connect(worker.deleteLater)
        workers.append(worker)
        worker.start()

    def on_check_requested() -> None:
        win.set_update_status("Checking for updates…")

        def done(result: updater.UpdateCheckResult) -> None:
            if not result.ok:
                win.set_update_status(f"Update check failed: {result.error}")
            elif result.update_available:
                win.set_update_status(
                    f"Update available: {result.remote_short}",
                    available=True, latest=result.remote_commit,
                )
            else:
                win.set_update_status(f"Up to date ({result.local_short}).")

        spawn(updater.check_for_update, done)

    def on_update_now() -> None:
        def done(message: str) -> None:
            success = message.startswith("Update pulled successfully")
            win.set_update_result(message, success=success)
            if success:
                win.reload_changelog()

        spawn(updater.run_git_pull, done)

    win.check_for_updates_requested.connect(on_check_requested)
    win.update_now_requested.connect(on_update_now)

    # QDialog.close() (the window's Close button, [X], or Esc) runs
    # QDialog's own closeEvent -> reject(), which emits finished(). That's
    # the standalone launcher's only exit path, so hook it to quit the app.
    win.finished.connect(lambda _result: app.quit())
    win.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.start(300)
    keepalive.timeout.connect(lambda: None)

    return app.exec()


def _self_test_checks() -> dict:
    """Exercise the frozen runtime without requiring a tray or AirPlay target."""
    import os

    if sys.platform != 'win32':
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from .appicon import app_icon
    from .caster import BINARY, preflight
    from .discovery import _is_ipv4
    from .spinner import ChasingArrows
    from . import windows_runtime

    app = QApplication.instance() or QApplication([APP_NAME, "--self-test"])
    icon = app_icon(theme='Default')
    assert not icon.isNull(), "application icon could not be rendered"
    app.setWindowIcon(icon)
    assert _is_ipv4("192.0.2.24"), "IPv4 discovery filter failed"

    spinner = ChasingArrows()
    spinner.start()
    spinner.stop()

    if not BINARY.is_file():
        raise RuntimeError(f"doubletake binary missing at {BINARY}")
    environment = windows_runtime.child_environment()
    with tempfile.TemporaryDirectory(prefix='screenmagnet-self-test-') as directory:
        with windows_runtime.external_dll_search():
            result = subprocess.run(
                [str(BINARY), "--help"], capture_output=True, text=True, timeout=30,
                cwd=directory, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
    help_text = result.stdout + result.stderr
    required = ("-monitor", "-target", "-hwaccel", "-pin", "-playout-floor-ms")
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise RuntimeError("doubletake is missing required flags: " + ", ".join(missing))
    report = {'qt_platform': app.platformName(), 'icon_rendered': True,
              'sender_help_checked': True, 'screen_count': len(app.screens())}
    if sys.platform == 'win32':
        problems = preflight()
        if problems:
            raise RuntimeError('; '.join(problems))
        runtime = windows_runtime.gstreamer_bin()
        import re
        plugins = ('d3d11screencapturesrc', 'd3d11convert', 'd3d11download',
                   'tcpclientsink', 'videoconvert', 'videoscale', 'x264enc',
                   'h264parse', 'wasapi2src', 'audioconvert', 'audioresample')
        with tempfile.TemporaryDirectory(prefix='screenmagnet-encode-test-') as directory:
            with windows_runtime.external_dll_search():
                version_result = subprocess.run([str(runtime / 'gst-inspect-1.0.exe'), '--version'],
                                                capture_output=True, text=True, timeout=20,
                                                cwd=directory, env=environment,
                                                creationflags=subprocess.CREATE_NO_WINDOW)
                version_match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_result.stdout)
                if (version_result.returncode or not version_match or
                        tuple(map(int, version_match.groups())) < (1, 28, 5)):
                    raise RuntimeError('GStreamer 1.28.5 or newer is required.')
                for plugin in plugins:
                    result = subprocess.run([str(runtime / 'gst-inspect-1.0.exe'), plugin],
                                            capture_output=True, text=True, timeout=20,
                                            cwd=directory, env=environment,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise RuntimeError(f'GStreamer plugin unavailable: {plugin}: {result.stderr[-500:]}')
                result = subprocess.run([
                    str(runtime / 'gst-launch-1.0.exe'), '-q', 'videotestsrc', 'num-buffers=8',
                    'pattern=black', '!', 'video/x-raw,width=320,height=240,framerate=30/1',
                    '!', 'videoconvert', '!', 'x264enc', 'tune=zerolatency',
                    'speed-preset=ultrafast', '!', 'h264parse', '!', 'fakesink', 'sync=false',
                ], capture_output=True, text=True, timeout=30, cwd=directory,
                    env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError(f'Synthetic H.264 encode failed: {result.stderr[-1000:]}')
        report.update(preflight=True, gstreamer_version=version_match.group(0),
                      gstreamer_plugins=list(plugins), synthetic_video_encode=True,
                      real_capture_tested=False, airplay_receiver_tested=False,
                      preview_note='Reconstructed Windows capture/audio; real TV validation remains pending.')
    spinner.deleteLater()
    app.processEvents()
    return report


def _run_self_test(report_path: Path | None = None) -> int:
    """Always return a bounded result, including when the report cannot be saved."""
    report = {'version': __version__, 'platform': sys.platform, 'passed': False}
    try:
        report.update(_self_test_checks())
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    if report_path is not None:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        except OSError as exc:
            report.update(passed=False, error=f'Cannot write self-test report: {exc}')
    if sys.stdout is not None:
        print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


def _set_windows_identity():
    if sys.platform == 'win32':
        import ctypes
        shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell32.SetCurrentProcessExplicitAppUserModelID('io.screenmagnet.ScreenMagnet')


def main() -> int:
    _set_windows_identity()
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--self-test" in sys.argv[1:]:
        import argparse
        parser = argparse.ArgumentParser(description='Bounded ScreenMagnet runtime check; no screen capture or casting.')
        parser.add_argument('--self-test', action='store_true')
        parser.add_argument('--report', type=Path)
        args = parser.parse_args()
        return _run_self_test(args.report)
    if "--settings" in sys.argv[1:]:
        return _run_settings_only([a for a in sys.argv if a != "--settings"])

    from .tray import ScreenMagnetTray

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    from .appicon import app_icon
    app.setWindowIcon(app_icon())
    # Plasma resolves the tray item's icon and name through the desktop file.
    app.setDesktopFileName("screenmagnet")
    # Tray-only app: closing the popup must not exit.
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray is available on this session.")
        return 1

    tray = ScreenMagnetTray(app)
    tray.show()

    # Let Ctrl+C through: Qt's event loop otherwise swallows SIGINT.
    signal.signal(signal.SIGINT, lambda *_: tray.quit())
    timer = QTimer()
    timer.start(300)
    timer.timeout.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
