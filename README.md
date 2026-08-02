# ScreenManget

Cast this machine's screen to a TV, from the system tray.

Linux has no built-in screen-mirroring sender. A phone or a Mac can throw its display at a
TV in two taps; a Linux desktop can't. This closes that gap on SteamOS, over AirPlay.

Click the tray icon → two arrows chase each other while it scans → your screens appear by
name → click one. If the TV wants a pairing code, a box appears inline. Pick which monitor
goes to the TV if you have more than one.

**Status: working.** Mirrors 1920×1080 @ 30 fps with audio, ~1.0 s end-to-end, at roughly
18 % of a 16-core CPU using software H.264.

---

## Layout

```
app/                  the PySide6 tray application
  screenmanget/
    tray.py           tray icon + popup panel
    spinner.py        the chasing-arrows scan indicator
    discovery.py      mDNS discovery, with reachability verification
    monitors.py       xrandr monitor enumeration
    caster.py         drives the AirPlay sender, parses its state
  tests/smoke_test.py 9 checks incl. live discovery
  run.sh
docs/                 measured research findings
patches/              our fixes to the AirPlay sender (see below)
spike/                build scripts + the latency measuring tool
lora/                 a local model that watches the build and writes about it
```

## Running it

```bash
app/run.sh
```

First run needs a venv. **It must be Python 3.13** — the default python on this box is 3.14
and PySide6 publishes no 3.14 wheels:

```bash
python3.13 -m venv ~/.local/share/screenmanget/venv
~/.local/share/screenmanget/venv/bin/pip install PySide6
```

Then the streaming backend, which lives in a container (see below):

```bash
spike/build-doubletake.sh
cd spike/doubletake && git apply ../../patches/0001-screenmanget-fixes.patch
distrobox enter screenmanget -- bash -lc 'cd ~/.claude/ScreenManget/spike/doubletake && go build -o bin/doubletake ./cmd/doubletake'
```

Verify with `app/tests/smoke_test.py`.

## Why a container

This host has **no H.264 GStreamer encoder at all** — `x264enc`, `openh264enc`, `vah264enc`
and `vaapih264enc` are all absent — and `steamos-readonly` is enabled, so they can't be
installed. The distrobox has them. The VA-API driver *is* present, so the silicon can encode;
GStreamer just has no plugin to reach it.

`xorg-xrandr` must be installed inside the container too. Without it the sender silently
falls back to capturing every monitor at once and squashing them into the TV.

## The engine

Streaming is done by [omarroth/doubletake](https://github.com/omarroth/doubletake) (Go,
LGPL-3.0+) — as far as we can tell the only working AirPlay *sender* for Linux. It is not
vendored here; `patches/` holds our changes against upstream `8ccea5f`.

Four fixes, all found by using it:

| Fix | Why |
|---|---|
| `videoscale` in the capture pipeline | It encoded the source monitor's native resolution while telling the receiver a different size. **Black screen** for anyone whose monitor ≠ their TV. |
| `-monitor <output>` | Previously always cropped to the primary monitor. |
| `-playout-floor-ms` | Overrides a 500 ms audio jitter margin that video inherits. Took latency 1.4 s → 1.0 s. |
| `-key-int` | Keyframe interval, for latency experiments. |

Still broken upstream: **`-hwaccel auto` picks NVENC on AMD** and the pipeline dies on the
first frame. Always pass `-hwaccel none` here.

## Latency

1.0 s end-to-end, measured with `spike/latency-clock.py` — put it on the mirrored monitor,
photograph the laptop and TV together, subtract.

About 500 ms of the original 1.4 s was the sender's own conservative playout floor, applied
to receivers that don't advertise FairPlay SAP. It exists because those receivers drop audio
they can't schedule ahead, and video inherits it to stay in sync. Turning it off is a real
trade: **audio then runs ~0.4 s behind and may glitch.** Good for watching a build scroll
past; not for anything where the sound matters. There's a toggle in the panel.

The remaining ~1.0 s is inside the TV and is not reachable from here. Two things that look
like they should help and measurably do not: shortening the keyframe interval, and disabling
audio. And note that *lowering* `-target-latency-ms` is a no-op — the code only ever raises
that value.

## Notes

- Discovery verifies a real TCP connect before offering a screen. mDNS caches serve records
  for devices that have already left the network, and connecting to one that isn't there
  hangs rather than failing.
- On Plasma 6 the tray is a StatusNotifierItem, so `QSystemTrayIcon.geometry()` is usually
  empty — the popup anchors on the cursor instead, and re-anchors whenever its content
  changes so a long list can't push it off-screen.
- Wi-Fi Direct / Miracast is impossible on this kernel: the mt76 driver only gained
  `P2P_DEVICE` in Linux 6.14. AirPlay needs none of it.

## Licence

The application is ours. `patches/` are modifications to doubletake and inherit its
**LGPL-3.0+**.
