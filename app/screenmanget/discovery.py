"""Find AirPlay screens on the LAN.

Uses avahi-browse rather than an in-process mDNS stack, because avahi-daemon owns
UDP 5353 on this machine and running a second responder alongside it is asking for
trouble.

Reachability is verified with a real TCP connect before a screen is offered as a
target. avahi has been observed serving stale records for a device that had already
left the network, and "connect to a sink that isn't there" is a hang, not an error.
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

AIRPLAY_SERVICE = "_airplay._tcp"
BROWSE_TIMEOUT = 8
REACH_TIMEOUT = 1.5


@dataclass(frozen=True)
class Screen:
    name: str
    host: str
    ip: str
    port: int
    model: str = ""

    @property
    def label(self) -> str:
        return self.name

    @property
    def sublabel(self) -> str:
        return f"{self.model} · {self.ip}" if self.model else self.ip


def _unescape(s: str) -> str:
    """avahi -p escapes as \\xxx decimal byte codes; also handles UTF-8 sequences."""
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 3 < len(s) and s[i + 1 : i + 4].isdigit():
            out.append(int(s[i + 1 : i + 4]))
            i += 4
        else:
            out.extend(s[i].encode())
            i += 1
    return out.decode("utf-8", errors="replace")


def _is_ipv4(addr: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address)
    except ValueError:
        return False


def _reachable(ip: str, port: int, timeout: float = REACH_TIMEOUT) -> bool:
    """True only if a TCP connect actually completes.

    avahi has been seen serving records for devices that already left the
    network, and it occasionally reports a link-local IPv6 address inside an
    IPv4 record -- so this is deliberately strict and never raises.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def discover(timeout: int = BROWSE_TIMEOUT) -> list[Screen]:
    """Browse for AirPlay receivers and return the ones that actually answer."""
    try:
        proc = subprocess.run(
            ["avahi-browse", "-rtp", AIRPLAY_SERVICE],
            capture_output=True,
            text=True,
            timeout=timeout + 4,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    seen: dict[str, Screen] = {}
    for line in proc.stdout.splitlines():
        if not line.startswith("="):
            continue
        parts = line.split(";")
        if len(parts) < 10 or parts[2] != "IPv4":
            continue
        name, host, ip, port_s, txt = (
            _unescape(parts[3]),
            parts[6],
            parts[7],
            parts[8],
            parts[9],
        )
        try:
            port = int(port_s)
        except ValueError:
            continue
        model = ""
        for field in txt.replace('"', " ").split():
            if field.startswith("model="):
                model = field[len("model=") :]
        # avahi repeats records per interface and sometimes puts a link-local
        # IPv6 address in an IPv4 record; keep only real IPv4. First wins.
        if not _is_ipv4(ip):
            continue
        if ip not in seen:
            seen[ip] = Screen(name=name, host=host, ip=ip, port=port, model=model)

    # Verify each one is really there before offering it as a target.
    return sorted(
        (s for s in seen.values() if _reachable(s.ip, s.port)),
        key=lambda s: s.name.lower(),
    )


class DiscoveryThread(QThread):
    """Runs discovery off the GUI thread so the spinner keeps spinning."""

    found = Signal(list)

    def run(self):
        try:
            self.found.emit(discover())
        except Exception:
            self.found.emit([])
