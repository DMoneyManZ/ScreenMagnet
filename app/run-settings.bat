@echo off
REM Launch ScreenMagnet's Settings/About window directly (no tray icon).
REM
REM This is the target for the "ScreenMagnet Settings" desktop shortcut --
REM it's the same launcher as run.bat, just with --settings appended so
REM __main__.py skips the tray and opens only the settings window.
REM
REM Requirements: same as run.bat (Python 3.13 venv with PySide6 installed).
REM GStreamer is not required just to view settings, but a missing venv
REM still is.
REM
REM First run:
REM   py -3.13 -m venv "%LOCALAPPDATA%\screenmagnet\venv"
REM   "%LOCALAPPDATA%\screenmagnet\venv\Scripts\pip" install PySide6 zeroconf

setlocal

if "%SCREENMAGNET_VENV%"=="" set "SCREENMAGNET_VENV=%LOCALAPPDATA%\screenmagnet\venv"
set "PY=%SCREENMAGNET_VENV%\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo venv not found at %SCREENMAGNET_VENV%
    echo.
    echo Create it with:
    echo   py -3.13 -m venv "%SCREENMAGNET_VENV%"
    echo   "%SCREENMAGNET_VENV%\Scripts\pip" install PySide6 zeroconf
    exit /b 1
)

cd /d "%~dp0"
start "" "%PY%" -m screenmagnet --settings %*
endlocal
