"""Entry point. Run via ../run.sh so the venv is used."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .tray import APP_NAME, ScreenMagnetTray


def main() -> int:
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
