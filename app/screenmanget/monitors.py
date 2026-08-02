"""Enumerate the monitors we could send to a screen."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

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


def list_monitors() -> list[Monitor]:
    try:
        out = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=6
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
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
    # Primary first, then left-to-right.
    return sorted(monitors, key=lambda mo: (not mo.primary, mo.x))
