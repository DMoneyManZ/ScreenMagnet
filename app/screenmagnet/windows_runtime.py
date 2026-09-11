"""Installed sender and external runtime lookup, without registry dependencies."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys

IS_WINDOWS = sys.platform == 'win32'


def sender_directory() -> Path:
    override = os.environ.get('SCREENMAGNET_DOUBLETAKE')
    if override:
        return Path(override)
    if IS_WINDOWS:
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent / 'doubletake'
        built = Path(__file__).resolve().parents[2] / 'build/doubletake'
        if (built / 'bin/doubletake.exe').is_file():
            return built
    return Path.home() / '.local/share/screenmagnet/doubletake'


def sender_working_directory() -> Path:
    if not IS_WINDOWS:
        return sender_directory()
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    directory = local / 'ScreenMagnet/sender-state'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def gstreamer_bin() -> Path | None:
    """Prefer the setup-verified standard installation over stale generic roots.

    SCREENMAGNET_GSTREAMER remains an intentional application-specific override.
    Setup and the Windows self-test verify versions/plugins at the selected root.
    """
    candidates = []
    if os.environ.get('SCREENMAGNET_GSTREAMER'):
        root = Path(os.environ['SCREENMAGNET_GSTREAMER'])
        candidates.extend((root / 'bin', root))
    for variable in ('ProgramW6432', 'ProgramFiles', 'LOCALAPPDATA'):
        value = os.environ.get(variable)
        if value:
            root = Path(value)
            candidates.extend((root / 'gstreamer/1.0/msvc_x86_64/bin',
                               root / 'Programs/gstreamer/1.0/msvc_x86_64/bin'))
    if IS_WINDOWS:
        candidates.append(Path(os.environ.get('SystemDrive', 'C:') + '/gstreamer/1.0/msvc_x86_64/bin'))
    for variable in ('GSTREAMER_1_0_ROOT_MSVC_X86_64', 'GSTREAMER_ROOT_X86_64', 'GSTREAMER_ROOT'):
        if os.environ.get(variable):
            root = Path(os.environ[variable])
            candidates.extend((root / 'bin', root))
    for name in ('gst-launch-1.0.exe', 'gst-inspect-1.0.exe'):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found).parent)
    for candidate in candidates:
        if all((candidate / tool).is_file() for tool in ('gst-launch-1.0.exe', 'gst-inspect-1.0.exe')):
            return candidate
    return None


def child_environment() -> dict[str, str]:
    """Use host libraries for external tools, leaving the Qt process untouched."""
    environment = dict(os.environ)
    if IS_WINDOWS:
        directory = gstreamer_bin()
        if directory:
            environment['PATH'] = str(directory) + os.pathsep + environment.get('PATH', '')
    elif sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
        # PyInstaller prepends _MEIPASS to the parent process's search path.
        # Host GStreamer (and the sender's descendants) need their own ABI.
        if 'LD_LIBRARY_PATH_ORIG' in environment:
            environment['LD_LIBRARY_PATH'] = environment['LD_LIBRARY_PATH_ORIG']
        else:
            environment.pop('LD_LIBRARY_PATH', None)
    return environment


@contextmanager
def external_dll_search():
    """Do not expose PyInstaller's bundled Qt DLL search path to GStreamer."""
    frozen_windows = sys.platform == 'win32' and getattr(sys, 'frozen', False)
    if frozen_windows:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel32.SetDllDirectoryW.restype = ctypes.c_int
        if not kernel32.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if frozen_windows:
            if not kernel32.SetDllDirectoryW(str(sys._MEIPASS)):
                raise ctypes.WinError(ctypes.get_last_error())
