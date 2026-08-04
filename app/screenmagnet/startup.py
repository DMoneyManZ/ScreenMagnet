"""Windows "launch at startup" toggle.

Adds or removes exactly one REG_SZ value under

    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

This is the same mechanism (and the same key) that OneDrive, Discord and
Teams already use on this machine -- Explorer runs the stored command once
at login. No scheduled task, no service, no extra process: disable() removes
the value cleanly and leaves nothing behind.

Only meaningful on Windows. Importable on other platforms (the rest of the
app is cross-platform), but enable()/disable() raise there and is_enabled()
just reports False.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover - exercised only on Windows in practice
    winreg = None  # type: ignore[assignment]

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "ScreenMagnet"


def _launch_command() -> str:
    """The command Explorer should run at login to start the tray app.

    Frozen build (PyInstaller): sys.executable *is* the app, and it starts
    the tray with no arguments -- just point straight at it.

    Running from source: relaunch this same interpreter windowlessly
    (pythonw.exe, not python.exe -- no console flash at login) against the
    screenmagnet package. sys.executable is already whichever venv launched
    the currently-running app (run.bat / run.sh resolve that at their own
    launch time), so reusing it adapts automatically instead of hardcoding
    a dev path. `python -m screenmagnet` normally relies on the current
    working directory landing on sys.path (run.bat does `cd /d "%~dp0"`
    first); a bare `pythonw -c` has no such cwd guarantee at login, so the
    app's directory is put on sys.path explicitly instead.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = exe  # fall back to whatever interpreter is actually running

    app_dir = Path(__file__).resolve().parent.parent  # .../app (holds the screenmagnet package)

    inline = (
        "import sys; "
        f"sys.path.insert(0, r'{app_dir}'); "
        "import runpy; "
        "runpy.run_module('screenmagnet.__main__', run_name='__main__')"
    )
    return f'"{pythonw}" -c "{inline}"'


def is_enabled() -> bool:
    """Whether the HKCU Run value currently exists."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> None:
    """Add (or overwrite) the Run value with the current launch command."""
    if winreg is None:
        raise RuntimeError("Launch at startup is only supported on Windows.")
    command = _launch_command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, command)


def disable() -> None:
    """Remove the Run value. A no-op (not an error) if it's already absent."""
    if winreg is None:
        raise RuntimeError("Launch at startup is only supported on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass
