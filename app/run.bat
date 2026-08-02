@echo off
REM Launch ScreenMagnet on Windows.
REM
REM Requirements:
REM   * Python 3.13 (PySide6 publishes no 3.14 wheels)
REM   * GStreamer for Windows, runtime, with the "bad" and "ugly" plugin sets.
REM     Its bin\ directory must be on PATH so gst-launch-1.0.exe resolves.
REM   * doubletake.exe built at spike\doubletake\bin\, or SCREENMAGNET_DOUBLETAKE
REM     pointing at wherever you put it.
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

where gst-launch-1.0.exe >nul 2>&1
if errorlevel 1 (
    echo WARNING: gst-launch-1.0.exe is not on PATH.
    echo Install GStreamer for Windows and add its bin\ directory to PATH,
    echo or casting will fail with a missing-encoder error.
    echo.
)

cd /d "%~dp0"
start "" "%PY%" -m screenmagnet %*
endlocal
