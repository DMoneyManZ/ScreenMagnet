"""Entry point. Run via ../run.sh so the venv is used."""

from __future__ import annotations

import signal
import subprocess
import sys

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


def _run_self_test() -> int:
    """Exercise the frozen runtime without requiring a tray or AirPlay target."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from .appicon import app_icon
    from .caster import BINARY
    from .discovery import _is_ipv4
    from .spinner import ChasingArrows

    app = QApplication.instance() or QApplication([APP_NAME, "--self-test"])
    assert not app_icon().isNull(), "application icon could not be rendered"
    assert _is_ipv4("192.0.2.24"), "IPv4 discovery filter failed"

    spinner = ChasingArrows()
    spinner.start()
    spinner.stop()

    if not BINARY.is_file():
        raise RuntimeError(f"doubletake binary missing at {BINARY}")
    result = subprocess.run(
        [str(BINARY), "--help"], capture_output=True, text=True, timeout=30
    )
    help_text = result.stdout + result.stderr
    required = ("-monitor", "-target", "-hwaccel", "-pin", "-playout-floor-ms")
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise RuntimeError("doubletake is missing required flags: " + ", ".join(missing))

    print(f"{APP_NAME} {__version__}: self-test passed")
    return 0


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--self-test" in sys.argv[1:]:
        return _run_self_test()
    if "--settings" in sys.argv[1:]:
        return _run_settings_only([a for a in sys.argv if a != "--settings"])

    from .tray import ScreenMagnetTray

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
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
