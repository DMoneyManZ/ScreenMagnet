<picture>
  <source media="(prefers-color-scheme: dark)" srcset="app/assets/screenmagnet-wordmark-dark.svg">
  <img alt="ScreenMagnet" src="app/assets/screenmagnet-wordmark-light.svg" width="360">
</picture>

**Cast this machine's screen to a TV, from the system tray.**

A phone or a Mac can throw its display at a TV in two taps. A Windows or Linux desktop
can't — there's no built-in sender. ScreenMagnet closes that gap, over AirPlay.

Click the tray icon → two arrows chase each other while it scans → your screens appear by
name → click one. If the TV wants a pairing code, a box appears inline. Pick which monitor
goes to the TV if you have more than one.

**Status: working.** Mirrors 1920×1080 @ 30 fps with audio (Linux) or video-only (Windows —
see [Known limitations](#known-limitations)), ~1.0s end-to-end latency, roughly 18% of a
16-core CPU using software H.264.

> Not affiliated with or endorsed by Apple. AirPlay is Apple's protocol and trademark;
> ScreenMagnet is an independent, reverse-engineered client, same territory as projects like
> shairport-sync and UxPlay.

---

## What it looks like

It lives in the system tray, out of the way until you want it:

<img src="docs/images/tray-icon.png" alt="The ScreenMagnet tray icon" width="220">

Click it and every AirPlay screen on your network is one more click away:

<img src="docs/images/panel-devices.png" alt="The ScreenMagnet panel listing discovered screens" width="425">

<sub>Device names above are examples.</sub>

---

## Install

**Windows:** grab `ScreenMagnet-Setup.exe` from the [latest release](../../releases/latest)
and run it. It bundles everything — the app, the AirPlay sender, GStreamer, and the VC++
runtime — nothing else to install first. You'll get one standard "allow this app to make
changes" prompt; after that it's fully unattended.

**Linux:** an AppImage is planned but not built yet — for now, run from source (below). If
you're on SteamOS or another host with no H.264 GStreamer encoder available, see
[Why a container](#why-a-container).

## Running from source

```bash
app/run.sh        # Linux
app\run.bat        # Windows
```

Needs **Python 3.13 specifically** — PySide6 publishes no 3.14 wheels yet:

```bash
python3.13 -m venv ~/.local/share/screenmagnet/venv
~/.local/share/screenmagnet/venv/bin/pip install PySide6 zeroconf
```

```powershell
py -3.13 -m venv $env:LOCALAPPDATA\screenmagnet\venv
& $env:LOCALAPPDATA\screenmagnet\venv\Scripts\pip install PySide6 zeroconf
```

Then point it at a built `doubletake` (the AirPlay sender — see [The engine](#the-engine)):

```bash
setx SCREENMAGNET_DOUBLETAKE "C:\path\to\doubletake"      # Windows, folder containing bin\doubletake.exe
export SCREENMAGNET_DOUBLETAKE=/path/to/doubletake         # Linux, folder containing bin/doubletake
```

Verify with `app/tests/smoke_test.py` — 9 checks, including live discovery on your LAN.

## Layout

```
app/                    the PySide6 tray application
  screenmagnet/
    tray.py              tray icon + popup panel
    spinner.py           the chasing-arrows scan indicator
    discovery.py         mDNS discovery, with reachability verification
    monitors.py          monitor enumeration (Qt, xrandr fallback)
    caster.py            drives the AirPlay sender, parses its state
  tests/smoke_test.py    9 checks incl. live discovery
  run.sh / run.bat
docs/                    measured research findings
patches/                 our fixes to the AirPlay sender (see below)
packaging/               installer build scripts (PyInstaller + Inno Setup)
spike/                   build scripts + the latency measuring tool
```

## Why a container

SteamOS (and similarly locked-down hosts) ship **no H.264 GStreamer encoder at all** —
`x264enc`, `openh264enc`, `vah264enc` and `vaapih264enc` are all absent — and a read-only
root filesystem blocks installing them. ScreenMagnet detects this: if your host has a usable
H.264 encoder already, it runs the sender directly (same as Windows); if not, it falls back to
running inside a [distrobox](https://github.com/89luca89/distrobox) container that has one.
The VA-API driver is often present even when the plugin isn't — the silicon can encode,
GStreamer just has no path to it without the container.

`xorg-xrandr` must be installed inside the container too. Without it the sender silently
falls back to capturing every monitor at once and squashing them into the TV.

## The engine

Streaming is done by [omarroth/doubletake](https://github.com/omarroth/doubletake) (Go,
LGPL-3.0+) — as far as we can tell the only working AirPlay *sender* for Linux, and now
Windows too. It is not vendored here; `patches/` holds our changes against upstream `8ccea5f`.

| Fix | Why |
|---|---|
| `videoscale` in the capture pipeline | Encoded the source monitor's native resolution while telling the receiver a different size — **black screen** for anyone whose monitor ≠ their TV. |
| `-monitor <output>` | Previously always cropped to the primary monitor. |
| `-playout-floor-ms` | Overrides a 500ms audio jitter margin that video inherits. Took latency 1.4s → 1.0s. |
| `-key-int` | Keyframe interval, for latency experiments. |
| Windows capture backend | `d3d11screencapturesrc` / DXGI Desktop Duplication, streamed over a loopback TCP socket instead of stdout (Windows' text-mode stdio otherwise corrupts the binary stream). |
| Real encoder probing | `-hwaccel auto` used to pick whatever encoder's element factory was *registered*, regardless of whether the hardware was actually present — killing the pipeline on its first frame (observed: NVENC selected on an AMD box). It now probes by encoding two real test frames first. |

## Known limitations

- **No audio on Windows yet.** `doubletake`'s audio capture only has a Linux backend
  (PulseAudio/PipeWire monitor sources) — casting on Windows currently sends video only.
  A Windows WASAPI loopback backend is a planned follow-up.
- **Linux AppImage not built yet** — run from source for now.

## Latency

1.0s end-to-end, measured with `spike/latency-clock.py` — put it on the mirrored monitor,
photograph the source and TV together, subtract.

About 500ms of the original 1.4s was the sender's own conservative playout floor, applied to
receivers that don't advertise FairPlay SAP. It exists because those receivers drop audio they
can't schedule ahead, and video inherits it to stay in sync. Turning it off is a real trade:
**audio then runs ~0.4s behind and may glitch.** Good for mirroring a desktop; not for anything
where the sound matters. There's a toggle in the panel.

The remaining ~1.0s is inside the TV and isn't reachable from here. Two things that look like
they should help and measurably don't: shortening the keyframe interval, and disabling audio.
And *lowering* `-target-latency-ms` is a no-op — the code only ever raises that value.

## Notes

- Discovery verifies a real TCP connect before offering a screen. mDNS caches serve records
  for devices that have already left the network, and connecting to one that isn't there
  hangs rather than failing.
- On Plasma 6 the tray is a StatusNotifierItem, so `QSystemTrayIcon.geometry()` is usually
  empty — the popup anchors on the cursor instead, and re-anchors whenever its content
  changes so a long list can't push it off-screen.
- On Windows, monitors are identified by device path (`\\.\DISPLAY1`) rather than name —
  select by the dropdown in the panel, not by editing config by hand.
- Wi-Fi Direct / Miracast is impossible on the reference SteamOS kernel: the mt76 driver only
  gained `P2P_DEVICE` in Linux 6.14. AirPlay needs none of it.

## License

ScreenMagnet itself is licensed under **GPL-3.0-or-later** (see [`LICENSE`](LICENSE)).
`patches/` are modifications to `doubletake` and inherit its **LGPL-3.0+**.
