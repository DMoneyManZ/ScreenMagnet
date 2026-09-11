"""Drive doubletake (the AirPlay sender) and report what it's doing.

Platform differences are confined to this module.

On Windows it runs directly: GStreamer for Windows ships x264enc and
openh264enc plus the hardware encoders, so there is nothing to containerise.

On Linux it also runs directly *if* the host has a usable H.264 encoder.
Most desktop distros do once GStreamer's "good/bad/ugly" plugin sets are
installed. When none is found (SteamOS: no H.264 encoder at all, and a
read-only root filesystem that blocks installing one) it falls back to
running inside a distrobox container that has the encoders instead.

Encoder selection is left on `auto`. It used to have to be forced to `none`
because doubletake picked an encoder whenever its element factory was merely
registered -- selecting NVENC on an AMD machine, where the pipeline died on the
first frame. It now probes by encoding two real frames, so `auto` degrades to
software correctly and finds hardware on machines that have it.
"""

from __future__ import annotations

import functools
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from . import windows_runtime

IS_WINDOWS = sys.platform.startswith("win")

CONTAINER = os.environ.get("SCREENMAGNET_CONTAINER", "screenmagnet")

# Installed Windows builds find their sibling sender without a registry value.
DOUBLETAKE_DIR = windows_runtime.sender_directory()
BINARY = DOUBLETAKE_DIR / "bin" / ("doubletake.exe" if IS_WINDOWS else "doubletake")

_H264_ENCODERS = ("x264enc", "openh264enc", "vah264enc", "vaapih264enc")

# Log lines we translate into UI state.
_READY = re.compile(r"screen capture started")
_CONNECTED = re.compile(r"connected to:\s*(?P<name>.+?)\s*\(model:")
_NEEDS_PIN = re.compile(r"M4 error: 2|PIN pairing failed|Enter the PIN")
_FATAL = re.compile(r"connect failed|no route to host|streaming error|pairing failed")


class CastError(Exception):
    pass


@functools.lru_cache(maxsize=1)
def _has_native_encoder() -> bool:
    """True if a usable H.264 GStreamer encoder is registered on this host.

    Cached: this shells out to gst-inspect-1.0 once per process, not once per
    cast. Irrelevant on Windows, where GStreamer for Windows always ships one.
    """
    gst_inspect = shutil.which("gst-inspect-1.0") or shutil.which("gst-inspect-1.0.exe")
    if not gst_inspect:
        return False
    for name in _H264_ENCODERS:
        try:
            if subprocess.run(
                [gst_inspect, name], capture_output=True, timeout=5
            ).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def _runs_natively() -> bool:
    """True if doubletake should be launched directly, false if it needs distrobox."""
    return IS_WINDOWS or _has_native_encoder()


def preflight() -> list[str]:
    """Return a list of problems that would stop a cast, empty if we're good."""
    problems = []
    if not BINARY.is_file():
        problems.append(f"doubletake binary missing at {BINARY}")
    if IS_WINDOWS:
        if windows_runtime.gstreamer_bin() is None:
            problems.append(
                "GStreamer runtime was not found. Run ScreenMagnet Setup to install "
                "the official Windows runtime, or set SCREENMAGNET_GSTREAMER to its folder."
            )
    elif _has_native_encoder():
        if not shutil.which("gst-launch-1.0"):
            problems.append("gst-launch-1.0 not on PATH")
    else:
        if not shutil.which("distrobox"):
            problems.append(
                "no H.264 encoder found and distrobox is not installed — "
                "either install GStreamer's 'bad'/'ugly' plugins, or install "
                "distrobox so the bundled container fallback can be used"
            )
    return problems


def _sender_argv(args: list[str]) -> tuple[str, list[str]]:
    """Build the (program, argv) pair that runs doubletake on this platform."""
    if _runs_natively():
        if IS_WINDOWS:
            # The Go sender's default is independent of cwd (it consults
            # XDG_CONFIG_HOME/USERPROFILE). Pin credentials to our user data.
            credentials = windows_runtime.sender_working_directory() / 'credentials.json'
            args = [*args, '-creds', str(credentials)]
        return str(BINARY), args
    inner = (
        f"cd {shlex.quote(str(DOUBLETAKE_DIR))} && "
        "exec ./bin/doubletake "
        + " ".join(shlex.quote(arg) for arg in args)
    )
    return "distrobox", ["enter", CONTAINER, "--", "bash", "-lc", inner]


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

        try:
            working_directory = windows_runtime.sender_working_directory() if _runs_natively() else None
            program, argv = _sender_argv(args)
        except OSError as exc:
            self.failed.emit(f"Cannot prepare sender data directory: {exc}")
            return
        self._proc = QProcess(self)
        proc = self._proc
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if working_directory is not None:
            self._proc.setWorkingDirectory(str(working_directory))
        environment = QProcessEnvironment()
        for key, value in windows_runtime.child_environment().items():
            environment.insert(key, value)
        self._proc.setProcessEnvironment(environment)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(lambda error, process=proc: self._on_process_error(process, error))
        try:
            with windows_runtime.external_dll_search():
                proc.start(program, argv)
                if IS_WINDOWS:
                    proc.waitForStarted(5000)
        except OSError as exc:
            self._proc = None
            proc.deleteLater()
            self.failed.emit(f"Could not start the sender: {exc}")

    def _on_process_error(self, proc, error):
        if proc is not self._proc:
            return
        if not self._reported_fatal:
            self._reported_fatal = True
            self.failed.emit(f"Sender process error: {proc.errorString()}")
        if error == QProcess.ProcessError.FailedToStart:
            self._proc = None
            proc.deleteLater()
            self.stopped.emit()

    def stop(self):
        if not self._proc:
            return
        proc, self._proc = self._proc, None
        if IS_WINDOWS and proc.processId():
            # Go's child GStreamer process must stop with this owned session.
            # No process-name matching: terminate only this sender's process tree.
            try:
                with windows_runtime.external_dll_search():
                    subprocess.run(['taskkill.exe', '/PID', str(proc.processId()), '/T', '/F'],
                                   capture_output=True, timeout=5,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                pass
        proc.terminate()
        if not proc.waitForFinished(4000):
            proc.kill()
            proc.waitForFinished(1000)
        proc.deleteLater()
        self._reap_orphans()
        self.stopped.emit()

    def _reap_orphans(self):
        """`distrobox enter` wraps the real process, so terminating the wrapper can
        leave the sender running. Anything launched directly needs none of this."""
        if _runs_natively():
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
