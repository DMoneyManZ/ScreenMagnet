"""Drive doubletake (the AirPlay sender) and report what it's doing.

Platform differences are confined to this module.

On Linux the sender runs inside a distrobox container, because SteamOS has no
H.264 GStreamer encoder at all and a read-only root filesystem. On Windows it
runs directly: GStreamer for Windows ships x264enc and openh264enc plus the
hardware encoders, so there is nothing to containerise.

Encoder selection is left on `auto`. It used to have to be forced to `none`
because doubletake picked an encoder whenever its element factory was merely
registered -- selecting NVENC on an AMD machine, where the pipeline died on the
first frame. It now probes by encoding two real frames, so `auto` degrades to
software correctly and finds hardware on machines that have it.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

IS_WINDOWS = sys.platform.startswith("win")

CONTAINER = "screenmagnet"

# Where the sender lives. Override with SCREENMAGNET_DOUBLETAKE -- on Windows
# there is no conventional location for it.
DOUBLETAKE_DIR = Path(
    os.environ.get("SCREENMAGNET_DOUBLETAKE")
    or (Path.home() / ".claude/ScreenMagnet/spike/doubletake")
)
BINARY = DOUBLETAKE_DIR / "bin" / ("doubletake.exe" if IS_WINDOWS else "doubletake")

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
    if not BINARY.exists():
        problems.append(f"doubletake binary missing at {BINARY}")
    if IS_WINDOWS:
        if not shutil.which("gst-launch-1.0.exe"):
            problems.append(
                "gst-launch-1.0.exe not on PATH — install GStreamer for Windows "
                "(runtime, with the 'bad' and 'ugly' plugin sets)"
            )
    else:
        if not shutil.which("distrobox"):
            problems.append("distrobox is not installed")
    return problems


def _sender_argv(args: list[str]) -> tuple[str, list[str]]:
    """Build the (program, argv) pair that runs doubletake on this platform."""
    if IS_WINDOWS:
        return str(BINARY), args
    inner = ["cd", str(DOUBLETAKE_DIR), "&&", "DISPLAY=:0", "exec", "./bin/doubletake"]
    inner += args
    return "distrobox", ["enter", CONTAINER, "--", "bash", "-lc", " ".join(inner)]


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

        args = [
            "-target", ip,
            "-hwaccel", "auto",
            "-fps", str(fps),
            "-target-latency-ms", "80",
        ]
        if low_latency:
            # doubletake imposes a 500ms playout floor on receivers without
            # FairPlay SAP as an audio jitter margin, and video inherits it to
            # stay in sync. Measured on an LG 43UK6090PUA: dropping it takes
            # end-to-end latency 1.4s -> 1.0s, at the cost of audio running
            # ~0.4s behind and possibly dropping. Worth it for a desktop
            # mirror; turn it off for anything where the sound matters.
            args += ["-playout-floor-ms", "0"]
        if monitor:
            args += ["-monitor", monitor]
        if pin:
            args += ["-pin", pin, "-pair"]

        program, argv = _sender_argv(args)

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if IS_WINDOWS:
            self._proc.setWorkingDirectory(str(DOUBLETAKE_DIR))
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.start(program, argv)

    def stop(self):
        if not self._proc:
            return
        proc, self._proc = self._proc, None
        proc.terminate()
        if not proc.waitForFinished(4000):
            proc.kill()
        self._reap_orphans()
        self.stopped.emit()

    def _reap_orphans(self):
        """`distrobox enter` wraps the real process, so terminating the wrapper can
        leave the sender running. Windows launches it directly and needs none of this."""
        if IS_WINDOWS:
            return
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
