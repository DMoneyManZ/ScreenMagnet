"""Find AirPlay screens on the LAN.

Uses python-zeroconf in-process rather than shelling out to avahi-browse: it
needs no daemon, no subprocess, and works the same on Linux and Windows.

Reachability is verified with a real TCP connect before a screen is offered as a
target. mDNS caches outlive the devices they describe -- avahi was observed
serving records for a TV that had already left the network -- and connecting to
a sink that isn't there hangs rather than failing.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

AIRPLAY_SERVICE = "_airplay._tcp.local."
BROWSE_SECONDS = 3.0
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


def _is_ipv4(addr: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address)
    except ValueError:
        return False


def _reachable(ip: str, port: int, timeout: float = REACH_TIMEOUT) -> bool:
    """True only if a TCP connect actually completes. Never raises."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


class _Collector(ServiceListener):
    def __init__(self, zc: Zeroconf):
        self._zc = zc
        self.found: dict[str, Screen] = {}

    # zeroconf calls these from its own thread
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def _record(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=2000)
        if not info:
            return

        addrs = [a for a in info.parsed_addresses() if _is_ipv4(a)]
        if not addrs:
            return
        ip = addrs[0]

        model = ""
        for k, v in (info.properties or {}).items():
            try:
                key = k.decode() if isinstance(k, bytes) else str(k)
                if key.lower() == "model" and v is not None:
                    model = v.decode() if isinstance(v, bytes) else str(v)
            except (UnicodeDecodeError, AttributeError):
                continue

        # The instance name is the human-facing one; strip the service suffix.
        label = name
        if label.endswith("." + type_):
            label = label[: -(len(type_) + 1)]

        self.found[ip] = Screen(
            name=label,
            host=(info.server or "").rstrip("."),
            ip=ip,
            port=info.port or 7000,
            model=model,
        )


def discover(seconds: float = BROWSE_SECONDS) -> list[Screen]:
    """Browse for AirPlay receivers and return the ones that actually answer."""
    zc = None
    try:
        zc = Zeroconf()
        collector = _Collector(zc)
        ServiceBrowser(zc, AIRPLAY_SERVICE, collector)
        time.sleep(seconds)
        candidates = list(collector.found.values())
    except OSError:
        # Port 5353 contention or no network; report nothing rather than crash.
        return []
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass

    return sorted(
        (s for s in candidates if _reachable(s.ip, s.port)),
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
