"""Support for "extend" casting -- treating the TV as new desktop space instead of
mirroring an existing monitor.

doubletake/GStreamer only ever capture displays Windows already knows about; neither can
fabricate a new display surface out of thin air. A real extended-desktop TV therefore
needs an actual virtual/indirect display *device* for Windows to enumerate, so the
capture backend has something to grab -- exactly like a real monitor. See
docs/EXTENDED-DISPLAY.md for the full feasibility writeup.

This module now drives a real (but never-yet-installed-in-this-session) candidate: the
open-source **VirtualDrivers/Virtual-Display-Driver** project (MIT, signed via
SignPath.io). A copy of its portable "VDD Control" app is vendored at
``packaging/windows/vendor/VirtualDisplayDriver-installer.zip`` (see that folder's
README) -- installing it is a one-time, one-UAC-click admin action this session cannot
perform on the user's behalf, so this module only ever *checks* and *drives* an
already-installed copy; it never launches the installer itself.

Three states matter, and they're genuinely different (research-confirmed, see
docs/EXTENDED-DISPLAY.md):

* **not installed** -- the driver package was never added to this Windows install.
  Needs the one-time admin install step above. ``is_installed()`` is False.
* **installed but disabled** -- the driver's adapter device (``Root\\MttVDD``, PnP
  friendly name ``"Virtual Display Driver"``) exists but is turned off. Windows treats
  enabling/disabling *any* device as a privileged operation -- ``Enable-PnpDevice``
  always needs an elevated token, no way around it, confirmed against the upstream
  project's own community scripts (``toggle-VDD.ps1``, ``virtual-driver-manager.ps1``,
  both self-elevate for exactly this reason). ``is_installed()`` True, ``is_enabled_now()``
  False.
* **installed and enabled** -- the virtual monitor is live and enumerable like any real
  screen. Both True.

The plan this module implements to avoid a UAC prompt on *every* cast (which would be
awful UX for a "cast at will from the tray" app): enable the device once and then never
disable it again from this app. The enabled/disabled bit is a persistent PnP device
setting -- once flipped on, it stays on (survives reboots) until someone disables it by
hand, so the elevation prompt in ``enable_virtual_display()`` should in practice fire at
most once per machine, not once per cast. Positioning the (already-enabled) virtual
monitor left/right of the primary is a plain per-user display-settings change (the same
class of action Windows' own Settings app lets a standard user do with no prompt), so
that part runs with no elevation at all, every cast, via a direct Win32
(``EnumDisplayDevices``/``ChangeDisplaySettingsEx``) call -- no VDD-specific API needed
once the device exists, confirmed by the upstream project's own positioning scripts
being nothing but a thin wrapper around the generic Windows CCD/DEVMODE display APIs.

**Genuinely untested.** This session has no admin rights and the driver has never
actually been installed on this machine, so nothing below has been exercised against a
real enumerated ``Root\\MttVDD`` device or a real virtual monitor -- only against "driver
absent", which every code path here does handle (returns False/None, never raises). See
the READ-THIS-FIRST warnings on ``enable_virtual_display()`` and
``_position_virtual_display()``.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Avoid flashing a console window behind the windowed (pythonw) tray app when
# shelling out to powershell.exe -- same pattern as updater.py's _CREATIONFLAGS.
_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

VALID_SIDES = ("left", "right")
DEFAULT_SIDE = "right"

# -- identifiers, sourced from the VirtualDrivers/Virtual-Display-Driver project's own
# .inf and its community PowerShell scripts (get_disp_num.ps1, toggle-VDD.ps1,
# virtual-driver-manager.ps1) -- see docs/EXTENDED-DISPLAY.md for the research trail.
# "IddSampleDriver Device HDR" is the older/dev-build friendly name; both are checked
# since which one a given install reports depends on driver version.
_FRIENDLY_NAMES = ("Virtual Display Driver", "IddSampleDriver Device HDR")
_INSTANCE_ID_PREFIX = "ROOT\\MttVDD"  # Get-PnpDevice .InstanceId prefix for the adapter
_MONITOR_MARKER = "MTT1337"  # spoofed EDID manufacturer/product code on the monitor sub-device

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# The download report for this session confirms only a .zip exists upstream (the
# project ships a portable app, not a classic installer) -- see the README next to it.
# Do not "fix" this to .exe: that file genuinely does not exist.
INSTALLER_ZIP = REPO_ROOT / "packaging" / "windows" / "vendor" / "VirtualDisplayDriver-installer.zip"

NOT_INSTALLED_MSG = (
    "Extended display is an experimental preview and needs the optional "
    "VirtualDrivers virtual display driver. It is not included with ScreenMagnet. "
    "Download VDD Control from https://github.com/VirtualDrivers/Virtual-Display-Driver/releases, "
    "follow that project's installation instructions, then restart ScreenMagnet. "
    "Installing a display driver requires Windows administrator approval. "
    "Mirror casting does not require this driver."
)

NOT_ENABLED_MSG = (
    "The virtual display driver is installed but currently turned off, and turning it "
    "on needs one admin approval from Windows (a UAC prompt) -- accept it if it "
    "appeared, then try again. This should only be needed once; ScreenMagnet leaves it "
    "on afterward instead of asking again for every cast."
)

NOT_ATTACHED_YET_MSG = (
    "The virtual display is on, but Windows hasn't listed it as a desktop display yet. "
    'Wait a few seconds and click "Cast as additional display" again.'
)


# ---------------------------------------------------------------------------
# Detection -- no admin required for any of this, read-only PnP/device queries.
# ---------------------------------------------------------------------------

def _query_pnp_device() -> dict | None:
    """Ask Windows (via PowerShell's ``Get-PnpDevice``, read-only, no admin needed --
    the exact lookup the upstream project's own scripts use, e.g.
    ``virtual-driver-manager.ps1``'s ``Get-VirtualDisplayDevice`` helper) whether the
    VDD adapter device is currently enumerated, and if so its live status.

    Returns ``None`` both when the device genuinely isn't present *and* when the query
    itself couldn't run at all (non-Windows, no PowerShell, timeout, bad JSON) --
    callers can't tell those apart from this alone, which is fine: both cases mean
    "nothing to offer right now", never a crash.
    """
    if not IS_WINDOWS:
        return None

    script = (
        "$d = Get-PnpDevice -Class Display -ErrorAction SilentlyContinue | "
        "Where-Object { "
        f"$_.FriendlyName -eq '{_FRIENDLY_NAMES[0]}' -or "
        f"$_.FriendlyName -eq '{_FRIENDLY_NAMES[1]}' -or "
        f"$_.InstanceId -like '{_INSTANCE_ID_PREFIX}*' "
        "} | Select-Object -First 1; "
        "if ($d) { $d | Select-Object FriendlyName,InstanceId,Status | ConvertTo-Json -Compress } "
        "else { 'null' }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATIONFLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout.strip() or "null")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_installed() -> bool:
    """True if the VDD adapter device is enumerated by Windows at all -- the driver
    package is present, regardless of whether it's currently switched on. This is the
    one-time-admin state: once true it should stay true (driver install is persistent)
    until someone actively uninstalls it; checking it never needs admin itself."""
    return _query_pnp_device() is not None


def is_enabled_now() -> bool:
    """True if the VDD adapter device is not just present but actively enabled right
    now -- i.e. Windows should be showing a real virtual monitor for it. False both
    when the driver isn't installed at all and when it's installed-but-disabled; use
    ``is_installed()`` to tell those two apart. Mirrors the upstream project's own
    ``toggle-VDD.ps1``, which treats ``Status -eq 'OK'`` as "on", anything else as
    "off"."""
    device = _query_pnp_device()
    return device is not None and device.get("Status") == "OK"


def status_summary() -> str:
    """One-line human-readable summary of current state, for tooltips/help text."""
    if not IS_WINDOWS:
        return "Extended display is Windows-only."
    device = _query_pnp_device()
    if device is None:
        return "Needs a one-time driver install -- click for details."
    if device.get("Status") == "OK":
        return "Virtual display driver is installed and on."
    return "Virtual display driver is installed but off -- click to turn it on (one-time admin prompt)."


# Backward-compat alias: older call sites imported is_available() to mean "go ahead and
# treat this as castable right now", which is is_enabled_now()'s job today. Kept only
# so any external/forgotten caller doesn't hard-crash on import.
is_available = is_enabled_now


# ---------------------------------------------------------------------------
# Enabling -- genuinely needs one admin approval (Windows OS restriction, not a
# choice made here). See module docstring for why this should only fire once.
# ---------------------------------------------------------------------------

def _elevated_enable_script() -> str:
    return (
        "$d = Get-PnpDevice -Class Display -ErrorAction SilentlyContinue | "
        "Where-Object { "
        f"$_.FriendlyName -eq '{_FRIENDLY_NAMES[0]}' -or "
        f"$_.FriendlyName -eq '{_FRIENDLY_NAMES[1]}' -or "
        f"$_.InstanceId -like '{_INSTANCE_ID_PREFIX}*' "
        "}; "
        "if ($d) { $d | Enable-PnpDevice -Confirm:$false }"
    )


def _enable_pnp_device_elevated(timeout: float = 90.0) -> bool:
    """Turn the VDD adapter on. ``Enable-PnpDevice`` always needs an elevated token --
    a hard Windows restriction, not a script choice, confirmed against the upstream
    project's own ``toggle-VDD.ps1``/``virtual-driver-manager.ps1``, which both
    self-elevate for exactly this step and nothing else. There is no way to skip the
    UAC prompt here. Deliberately only ever *enables*, never disables -- see module
    docstring for why (so this prompt should fire at most once per machine, not once
    per cast).

    Runs an elevated child PowerShell (``Start-Process -Verb RunAs -Wait``, the same
    self-elevation idiom the upstream scripts use) and waits for it. If the user
    declines the UAC prompt, ``Start-Process`` throws inside that child, which surfaces
    here as a non-zero exit code -- treated as "couldn't enable", not a crash.

    **Untested.** No admin rights this session, driver never installed -- this exact
    code path (including the temp .ps1 file handoff, used instead of trying to
    shell-escape the script into a single -Command string) has never actually run.
    """
    if not IS_WINDOWS:
        return False

    script = _elevated_enable_script()
    ps1_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as f:
            f.write(script)
            ps1_path = f.name

        launcher = (
            "Start-Process -FilePath powershell.exe -Verb RunAs -Wait -WindowStyle Hidden "
            f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','{ps1_path}'"
        )
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", launcher],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATIONFLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if ps1_path:
            try:
                Path(ps1_path).unlink(missing_ok=True)
            except OSError:
                pass

    if proc.returncode != 0:
        # Most likely: the user clicked "No" on the UAC prompt.
        return False
    return is_enabled_now()


# ---------------------------------------------------------------------------
# Positioning + monitor identification -- no admin needed, plain per-user
# display-settings changes via the classic Win32 API (see docs/EXTENDED-DISPLAY.md
# §5 for why this API was picked over the newer CCD SetDisplayConfig path).
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    from ctypes import wintypes

    class _DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    class _POINTL(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _DEVMODE_PRINTER_UNION_S1(ctypes.Structure):
        _fields_ = [
            ("dmOrientation", ctypes.c_short),
            ("dmPaperSize", ctypes.c_short),
            ("dmPaperLength", ctypes.c_short),
            ("dmPaperWidth", ctypes.c_short),
            ("dmScale", ctypes.c_short),
            ("dmCopies", ctypes.c_short),
            ("dmDefaultSource", ctypes.c_short),
            ("dmPrintQuality", ctypes.c_short),
        ]

    class _DEVMODE_DISPLAY_UNION_S2(ctypes.Structure):
        _fields_ = [
            ("dmPosition", _POINTL),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
        ]

    class _DEVMODE_UNION(ctypes.Union):
        _fields_ = [("printer", _DEVMODE_PRINTER_UNION_S1), ("display", _DEVMODE_DISPLAY_UNION_S2)]
        # Promotes both members' own fields (dmOrientation..., dmPosition...) up to
        # this union's namespace, so a further anonymous union on DEVMODEW itself
        # (below) exposes e.g. `devmode.dmPosition` directly instead of needing
        # `devmode.u1.display.dmPosition`.
        _anonymous_ = ("printer", "display")

    class _DEVMODEW(ctypes.Structure):
        _anonymous_ = ("u1",)
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("u1", _DEVMODE_UNION),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlagsOrNup", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    _DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
    _ENUM_CURRENT_SETTINGS = -1
    _ENUM_REGISTRY_SETTINGS = -2
    _DM_POSITION = 0x00000020
    _CDS_UPDATEREGISTRY = 0x00000001
    _CDS_NORESET = 0x10000000
    _DISP_CHANGE_SUCCESSFUL = 0

    _user32 = ctypes.windll.user32
    _user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DISPLAY_DEVICEW), wintypes.DWORD,
    ]
    _user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    _user32.EnumDisplaySettingsW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DEVMODEW),
    ]
    _user32.EnumDisplaySettingsW.restype = wintypes.BOOL
    _user32.ChangeDisplaySettingsExW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(_DEVMODEW), wintypes.HWND, wintypes.DWORD, wintypes.LPVOID,
    ]
    _user32.ChangeDisplaySettingsExW.restype = ctypes.c_long
else:
    _user32 = None


def _find_virtual_adapter_and_primary() -> tuple[str | None, str | None]:
    """Scan every display adapter Windows currently knows about (``EnumDisplayDevicesW``)
    for one whose attached monitor carries the VDD signature, and separately note which
    adapter is the primary. Returns (virtual adapter device name, primary adapter device
    name), e.g. ``('\\\\.\\DISPLAY3', '\\\\.\\DISPLAY1')`` -- either may be ``None``."""
    if not IS_WINDOWS or _user32 is None:
        return None, None

    virtual_name: str | None = None
    primary_name: str | None = None
    i = 0
    while True:
        adapter = _DISPLAY_DEVICEW()
        adapter.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(None, i, ctypes.byref(adapter), 0):
            break
        if adapter.StateFlags & _DISPLAY_DEVICE_PRIMARY_DEVICE:
            primary_name = adapter.DeviceName

        j = 0
        while True:
            mon = _DISPLAY_DEVICEW()
            mon.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
            if not _user32.EnumDisplayDevicesW(adapter.DeviceName, j, ctypes.byref(mon), 0):
                break
            if _MONITOR_MARKER in mon.DeviceID or any(
                name in mon.DeviceString for name in _FRIENDLY_NAMES
            ):
                virtual_name = adapter.DeviceName
            j += 1
        i += 1
    return virtual_name, primary_name


def find_virtual_display_name() -> str | None:
    """The Win32 GDI adapter device name (e.g. ``'\\\\.\\DISPLAY3'``) for the VDD
    virtual monitor, if Windows currently has one enumerated as a desktop display. This
    is the same identifier Qt's ``QScreen.name()`` reports on Windows (see
    monitors.py's module docstring), so it doubles as the ``monitor`` name to hand
    ``Caster.start()`` once the display is up -- confirmed by the research as the right
    integration point ("a virtual display would just show up as another entry"), though
    the actual value has never been observed against a real installed driver."""
    try:
        virtual_name, _primary = _find_virtual_adapter_and_primary()
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    return virtual_name


def _current_devmode(device_name: str) -> "_DEVMODEW | None":
    for mode_num in (_ENUM_CURRENT_SETTINGS, _ENUM_REGISTRY_SETTINGS):
        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        if _user32.EnumDisplaySettingsW(device_name, mode_num, ctypes.byref(dm)):
            return dm
    return None


def _position_virtual_display(side: str) -> bool:
    """Best-effort: place the virtual monitor left/right of the primary using the
    classic ``EnumDisplayDevices``/``ChangeDisplaySettingsEx`` Win32 pair (DEVMODE's
    ``dmPosition``) -- the same API any ordinary second monitor is repositioned with,
    nothing VDD-specific. No admin needed: rearranging monitor positions is a per-user
    setting on stock Windows. See docs/EXTENDED-DISPLAY.md §5 for why this API was
    picked over the newer path-based CCD ``SetDisplayConfig``.

    Failure is swallowed and reported as ``False``, never raised -- a cast against a
    mispositioned-but-working virtual monitor is a much better outcome than losing the
    whole cast over a cosmetic placement step.

    **Completely unverified end-to-end.** There is no enumerated virtual monitor to
    test this against in this environment; the ctypes structure layouts and flag values
    are transcribed from the documented ``DEVMODEW``/``DISPLAY_DEVICEW`` Win32 ABI, not
    exercised against real hardware.
    """
    if not IS_WINDOWS or _user32 is None:
        return False
    try:
        virtual_name, primary_name = _find_virtual_adapter_and_primary()
        if not virtual_name or not primary_name:
            return False

        primary_dm = _current_devmode(primary_name)
        virtual_dm = _current_devmode(virtual_name)
        if primary_dm is None or virtual_dm is None:
            return False

        if side == "left":
            virtual_dm.dmPosition.x = -int(virtual_dm.dmPelsWidth)
            virtual_dm.dmPosition.y = 0
        else:
            virtual_dm.dmPosition.x = int(primary_dm.dmPelsWidth)
            virtual_dm.dmPosition.y = 0
        virtual_dm.dmFields |= _DM_POSITION

        _user32.ChangeDisplaySettingsExW(
            virtual_name, ctypes.byref(virtual_dm), None,
            _CDS_UPDATEREGISTRY | _CDS_NORESET, None,
        )
        result = _user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
        return result == _DISP_CHANGE_SUCCESSFUL
    except (OSError, AttributeError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Public orchestration entry point
# ---------------------------------------------------------------------------

def enable_virtual_display(side: str = DEFAULT_SIDE) -> bool:
    """Turn the virtual monitor on (admin, at most once -- see module docstring) and
    place it beside the primary per ``side`` (no admin). Returns ``True`` once the
    device is enabled -- positioning failure is not fatal to the return value, since a
    working-but-mispositioned display is still castable; callers that care can check
    ``find_virtual_display_name()`` separately once this returns ``True``.

    Blocking: this can wait on a UAC dialog the user hasn't clicked yet. Callers should
    run it off the Qt GUI thread (see ``tray.py``'s use via ``updater.CallWorker``) so a
    slow-to-respond UAC prompt doesn't freeze the panel.

    Deliberately does one ``Get-PnpDevice`` query up front (not separate
    ``is_installed()``/``is_enabled_now()`` calls) to avoid stacking up several
    ~1-second PowerShell spawns in the already-installed-and-enabled steady state,
    which is the common case on every repeat cast once the one-time setup is done.
    """
    if side not in VALID_SIDES:
        side = DEFAULT_SIDE
    device = _query_pnp_device()
    if device is None:
        return False  # not installed
    already_on = device.get("Status") == "OK"
    if not already_on:
        if not _enable_pnp_device_elevated():
            return False
        already_on = True  # _enable_pnp_device_elevated() already re-verified this
    _position_virtual_display(side)  # best-effort, deliberately not fatal
    return already_on
