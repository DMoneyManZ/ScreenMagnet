#!/usr/bin/env python3
"""ScreenMagnet smoke test.

Checks the things that actually break: imports, the backend binary, discovery
plumbing, monitor enumeration, and that the Qt widgets can be constructed
offscreen. Does NOT start a cast -- that would put a picture on a TV.

    ./tests/smoke_test.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

PASS, FAIL, WARN = "  ok  ", " FAIL ", " warn "
failures = 0


def check(label: str, fn):
    global failures
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 - smoke test reports everything
        ok, detail = False, f"{type(e).__name__}: {e}"
    if ok is None:
        print(f"[{WARN}] {label}: {detail}")
        return
    print(f"[{PASS if ok else FAIL}] {label}" + (f": {detail}" if detail else ""))
    if not ok:
        failures += 1


def t_pyside():
    import PySide6

    return True, f"PySide6 {PySide6.__version__}"


def t_modules():
    from screenmagnet import caster, discovery, monitors, spinner, tray  # noqa: F401

    return True, "all modules import"


def t_binary():
    from screenmagnet.caster import BINARY

    return BINARY.exists(), str(BINARY)


def t_preflight():
    from screenmagnet.caster import preflight

    problems = preflight()
    return (not problems), ("; ".join(problems) if problems else "distrobox + doubletake binary present")


def t_monitors():
    from screenmagnet.monitors import list_monitors

    mons = list_monitors()
    if not mons:
        return None, "no monitors enumerated (headless?)"
    return True, ", ".join(f"{m.name} {m.width}x{m.height}" for m in mons)


def t_zeroconf():
    import zeroconf

    from screenmagnet.discovery import _is_ipv4

    assert _is_ipv4("192.168.1.24") and not _is_ipv4("fe80::1"), "IPv4 filter wrong"
    return True, f"python-zeroconf {zeroconf.__version__}, IPv4 filter ok"


def t_discovery():
    from screenmagnet.discovery import discover

    screens = discover(seconds=4)
    if not screens:
        return None, "no AirPlay screens answered (TV off?)"
    return True, ", ".join(f"{s.name} @ {s.ip}" for s in screens)


def t_widgets():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from screenmagnet.spinner import ChasingArrows
    from screenmagnet.tray import Panel, ScreenMagnetTray, app_icon

    app = QApplication.instance() or QApplication([])
    icon = app_icon()
    assert not icon.isNull(), "app icon is null"
    tray = ScreenMagnetTray(app)
    assert isinstance(tray.panel, Panel)
    spin = ChasingArrows()
    spin.start()
    spin.stop()
    tray.panel.show_screens([])
    tray.panel.refresh_monitors(None)
    return True, "tray, panel, spinner construct"


def t_doubletake_flags():
    from screenmagnet.caster import BINARY, CONTAINER, DOUBLETAKE_DIR, IS_WINDOWS

    if IS_WINDOWS:
        cmd = [str(BINARY), "--help"]
    else:
        cmd = ["distrobox", "enter", CONTAINER, "--", "bash", "-lc",
               f"cd {DOUBLETAKE_DIR} && ./bin/doubletake --help 2>&1"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=90).stdout
    missing = [f for f in ("-monitor", "-target", "-hwaccel", "-pin", "-playout-floor-ms") if f not in out]
    return (not missing), ("missing flags: " + ", ".join(missing) if missing else "-monitor/-target/-hwaccel/-pin/-playout-floor-ms present")


if __name__ == "__main__":
    print("ScreenMagnet smoke test\n")
    check("PySide6 available", t_pyside)
    check("app modules import", t_modules)
    check("doubletake binary built", t_binary)
    check("preflight (distrobox/binary)", t_preflight)
    check("monitor enumeration", t_monitors)
    check("zeroconf + IPv4 filter", t_zeroconf)
    check("doubletake CLI flags", t_doubletake_flags)
    check("Qt widgets construct (offscreen)", t_widgets)
    check("live AirPlay discovery", t_discovery)

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        sys.exit(1)
    print("all checks passed")
