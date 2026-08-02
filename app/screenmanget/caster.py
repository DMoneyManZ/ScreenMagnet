"""Drive doubletake (the AirPlay sender) and report what it's doing.

doubletake runs inside a distrobox container because the SteamOS host has no H.264
GStreamer encoder at all and its root filesystem is read-only. The container has
x264enc + openh264enc.

Encoder selection is left on `auto`. It used to have to be forced to `none`
because doubletake picked an encoder whenever its element factory was merely
registered -- selecting NVENC on this AMD machine, where the pipeline died on
the first frame. It now probes by encoding two real frames, so `auto` degrades
to software correctly here and will find hardware on machines that have it.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

CONTAINER = "screenmanget"
DOUBLETAKE_DIR = Path.home() / ".claude/ScreenManget/spike/doubletake"
BINARY = DOUBLETAKE_DIR / "bin/doubletake"

# Log lines we translate into UI state.
_READY = re.compile(r"screen capture started")
_CONNECTED = re.compile(r"connected to:\s*(?P<name>.+?)\s*\(model:")
_NEEDS_PIN = re.compile(r"M4 error: 2|PIN pairing failed|Enter the PIN")
_FATAL = re.compile(r"connect failed|no route to host|streaming error|pairing failed")


class CastError(Exception):
    pass


def preflight() -> list[str]:
    """Return a list of problems that would stop a cast, empty if we're good."""
    problems = []
    if not shutil.which("distrobox"):
        problems.append("distrobox is not installed")
    if not BINARY.exists():
        problems.append(f"doubletake binary missing at {BINARY}")
    return problems


class Caster(QObject):
    """Owns one streaming session."""

    connected = Signal(str)      # receiver name
    streaming = Signal()
    needs_pin = Signal()
    failed = Signal(str)
    stopped = Signal()
    log_line = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._target: str | None = None
        self._reported_fatal = False

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        ip: str,
        monitor: str | None = None,
        pin: str | None = None,
        fps: int = 30,
        low_latency: bool = True,
    ):
        if self.active:
            self.stop()

        problems = preflight()
        if problems:
            self.failed.emit("; ".join(problems))
            return

        self._target = ip
        self._reported_fatal = False

        inner = [
            f"cd {DOUBLETAKE_DIR}",
            "&&",
            "DISPLAY=:0",
            "exec",
            "./bin/doubletake",
            "-target", ip,
            "-hwaccel", "auto",          # probes encoders for real; falls back to x264enc
            "-fps", str(fps),
            "-target-latency-ms", "80",
        ]
        if low_latency:
            # doubletake imposes a 500ms playout floor on receivers without
            # FairPlay SAP (this LG is one) as an audio jitter margin, and video
            # inherits it to stay in sync. Measured on the LG 43UK6090PUA:
            # dropping it takes end-to-end latency 1.4s -> 1.0s, at the cost of
            # audio running ~0.4s behind and possibly dropping. Worth it for a
            # desktop mirror; turn off for anything where the sound matters.
            inner += ["-playout-floor-ms", "0"]
        if monitor:
            inner += ["-monitor", monitor]
        if pin:
            inner += ["-pin", pin, "-pair"]

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.start("distrobox", ["enter", CONTAINER, "--", "bash", "-lc", " ".join(inner)])

    def stop(self):
        if not self._proc:
            return
        proc, self._proc = self._proc, None
        proc.terminate()
        if not proc.waitForFinished(4000):
            proc.kill()
        # distrobox enter wraps the real process; make sure the inner one is gone.
        self._reap_orphans()
        self.stopped.emit()

    def _reap_orphans(self):
        try:
            out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if "bin/doubletake" in line and "grep" not in line:
                    try:
                        os.kill(int(line.split()[0]), signal.SIGTERM)
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass

    def _on_output(self):
        if not self._proc:
            return
        text = bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        for line in text.splitlines():
            if not line.strip():
                continue
            self.log_line.emit(line)
            if m := _CONNECTED.search(line):
                self.connected.emit(m["name"])
            if _NEEDS_PIN.search(line):
                self.needs_pin.emit()
            elif _READY.search(line):
                self.streaming.emit()
            elif _FATAL.search(line) and not self._reported_fatal:
                self._reported_fatal = True
                self.failed.emit(line.strip())

    def _on_finished(self, _code, _status):
        self._proc = None
        self.stopped.emit()
