#!/usr/bin/env python3
"""Offline smoke test used for Python 3.13/3.14 compatibility CI."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import __version__ as pyside_version
from PySide6.QtWidgets import QApplication

from screenmagnet import __version__
from screenmagnet import caster, discovery, monitors, spinner, tray, virtual_display


def main() -> int:
    app = QApplication.instance() or QApplication(["ScreenMagnet-ci"])
    assert not tray.app_icon().isNull()
    assert discovery._is_ipv4("192.0.2.24")
    assert not discovery._is_ipv4("fe80::1")
    assert isinstance(monitors.list_monitors(), list)
    assert caster.BINARY.name == "doubletake"
    assert virtual_display.IS_WINDOWS is False

    widget = spinner.ChasingArrows()
    widget.start()
    widget.stop()

    print(
        f"ScreenMagnet {__version__}: Python {sys.version.split()[0]}, "
        f"PySide6 {pyside_version}, offline smoke test passed"
    )
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
