"""Enumerate the monitors we could send to a screen.

Qt is the source of truth so this works identically on X11, Wayland and Windows.
xrandr remains as a fallback for the case where no Qt application exists yet.

Two things to be careful about:

* ``QScreen.geometry()`` is in LOGICAL pixels. On a 125% display a 1920x1080
  panel reports 1536x864. Capture crops are in physical pixels, so every
  dimension here is scaled by ``devicePixelRatio``.
* ``QScreen.name()`` matches the xrandr output name on X11 ("DisplayPort-1",
  "eDP"), which is exactly what doubletake's ``-monitor`` flag expects. On
  Windows it is a device path like ``\\\\.\\DISPLAY1`` instead, so a Windows
  capture backend must select by index or geometry rather than by name.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from . import windows_runtime

# "DisplayPort-1 connected primary 1920x1080+0+0 (normal left ...)"
_GEOM = re.compile(
    r"^(?P<name>\S+)\s+connected\s+(?P<primary>primary\s+)?"
    r"(?P<w>\d+)x(?P<h>\d+)\+(?P<x>\d+)\+(?P<y>\d+)"
)


@dataclass(frozen=True)
class Monitor:
    name: str
    width: int
    height: int
    x: int
    y: int
    primary: bool

    @property
    def label(self) -> str:
        star = " ★" if self.primary else ""
        return f"{self.name}  {self.width}×{self.height}{star}"


def _from_qt() -> list[Monitor]:
    """Enumerate via Qt. Returns [] when no QGuiApplication exists yet."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return []

    app = QGuiApplication.instance()
    if app is None:
        return []

    primary = QGuiApplication.primaryScreen()
    monitors = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        # Logical -> physical pixels; capture crops are physical.
        r = s.devicePixelRatio() or 1.0
        monitors.append(
            Monitor(
                name=s.name() or "screen",
                width=int(round(g.width() * r)),
                height=int(round(g.height() * r)),
                x=int(round(g.x() * r)),
                y=int(round(g.y() * r)),
                primary=(s == primary),
            )
        )
    return monitors


def _from_xrandr() -> list[Monitor]:
    """Fallback for when Qt isn't up yet. X11 only; already physical pixels."""
    try:
        out = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=6,
            env=windows_runtime.child_environment(),
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    monitors = []
    for line in out.splitlines():
        m = _GEOM.match(line)
        if not m:
            continue
        monitors.append(
            Monitor(
                name=m["name"],
                width=int(m["w"]),
                height=int(m["h"]),
                x=int(m["x"]),
                y=int(m["y"]),
                primary=bool(m["primary"]),
            )
        )
    return monitors


def list_monitors() -> list[Monitor]:
    monitors = _from_qt() or _from_xrandr()
    # Primary first, then left to right.
    return sorted(monitors, key=lambda mo: (not mo.primary, mo.x))
