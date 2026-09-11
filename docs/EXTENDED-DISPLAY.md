# "Cast as additional display" — feasibility

## Status: optional external driver; live extended-display validation pending

ScreenMagnet's Windows setup **does not bundle or install a virtual-display
driver**. When the driver is missing, the app points to the official
[VirtualDrivers/Virtual-Display-Driver releases](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases).
Obtain the driver from upstream and follow that release's installation
instructions; driver installation requires Windows administrator approval.
Restart ScreenMagnet afterward. Mirror casting does not require this driver.

### What has and has not been established

Earlier development notes recorded read-only checks of `is_installed()`,
`is_enabled_now()`, and `find_virtual_display_name()` on a Windows machine without
the driver. Those checks returned no installed/enabled driver or matching virtual
monitor. They establish only that absent-driver behavior on that machine.

The implementation in [virtual_display.py](../app/screenmagnet/virtual_display.py)
checks the PnP adapter, can request elevation to enable an installed adapter, and
attempts to position its virtual monitor beside the primary display. The tray
then re-enumerates monitors before starting the sender. **The complete
install/enable/position/cast sequence has not been verified against an installed
driver and real receiver.** UAC cancellation, display attachment timing,
monitor positioning, and end-to-end capture remain live-hardware checks.

The preview sender is rebuilt from the pinned upstream source and project patch.
Its Windows capture/audio reconstruction is distinct from the historical
video-only binary. Source, unit, or package smoke checks do not establish that
reconstructed capture, extended-display streaming, or audio works on a real TV.

### Why installed/enabled/attached are three different questions, and what each means

- **Not installed** → `cast_to("extend")` shows a message linking the official
  upstream releases and explains the separate driver installation. ScreenMagnet
  does not launch a driver installer itself.
- **Installed but disabled** → Windows treats enabling *any* device as a privileged
  operation (`Enable-PnpDevice` always needs an elevated token — a hard OS restriction,
  confirmed against the upstream project's own scripts, not a design choice made here).
  `enable_virtual_display()` self-elevates for this one step and, deliberately, only
  ever *enables* — it never disables the device again itself. Since the PnP
  enabled/disabled bit is persistent (survives reboots), this UAC prompt should in
  practice fire at most once per machine, not once per cast — the alternative
  (disabling between casts for tidiness) would mean a fresh UAC prompt every single
  cast start, which the research flagged as a real UX cost worth avoiding entirely.
- **Enabled but not yet attached as a desktop display** → a narrow timing window right
  after `Enable-PnpDevice` where Windows/Qt haven't finished surfacing it as an
  enumerable screen yet. Surfaced as its own message rather than silently retrying
  forever or casting to the wrong monitor.

## Why this isn't just a doubletake flag

`doubletake` captures a display surface the OS already knows about
(`d3d11screencapturesrc` / DXGI Desktop Duplication on Windows) and streams it.
It has no way to fabricate a new one. "Cast as additional display" — the TV
becoming real desktop space you can drag windows onto, not a mirror — requires
Windows itself to have an actual virtual/indirect display device registered
*before* doubletake ever runs, so there's a real surface to capture.

## Windows' own wireless-display "extend" mode doesn't apply here

Windows can already do wireless extend — but only to a **Miracast** receiver,
and `docs/RESEARCH-FINDINGS.md` §10 already established this TV answers
AirPlay only. It was tested directly: with the TV's Screen Share (Wi-Fi Direct
Miracast) open, it advertised no `_display._tcp` and kept 7236/7250 closed.
There's no Miracast session to extend into on this receiver, independent of
any kernel/driver constraint on the sending side.

## What a real implementation needs

An indirect display driver (Microsoft's **IddCx** framework) registered with
Windows, creating a virtual monitor that Explorer/DWM treats as a normal
extended display — at which point `d3d11screencapturesrc` can capture *that*
surface like any other and doubletake streams it as usual.

Concretely, that means:

- A driver package (INF + IddCx driver binary) installed via `pnputil`, which
  needs an admin prompt — one more UAC click, same category as the GStreamer/
  VC++ prereqs the installer already chains, so no new *class* of requirement.
- The driver needs to be signed (or the box needs test-signing enabled), which
  is the actual friction: shipping an unsigned driver either fails outright on
  a default Windows 11 install or requires the user to weaken driver signature
  enforcement, which is not something to ask a general audience to do.
- The following candidates were surveyed during earlier research. These are
  historical findings, not a list of dependencies bundled with ScreenMagnet.
  Current packages build the sender from source and direct users upstream for
  the optional driver. Any future driver-bundling decision would require its
  own provenance, licensing, signing, and maintenance review. Re-check upstream
  before relying on the historical candidate details:
  - **VirtualDrivers/Virtual-Display-Driver** (github.com/VirtualDrivers/
    Virtual-Display-Driver, formerly itsmikethetech's repo, now org-maintained).
    MIT licensed. Reportedly ships an installer code-signed via SignPath.io's
    free open-source signing path, so it's claimed to avoid needing
    test-signing mode or disabled driver signature enforcement on a normal
    Windows 11 install — the strongest "closer to one-click" candidate found.
    Config via `vdd_settings.xml`; community PowerShell scripts drive it
    headlessly (install/enable/disable/change-resolution) without a GUI, which
    would matter if ScreenMagnet ever shells out to it rather than bundling
    one. Caveat: open issues reportedly describe signature/cert friction on
    Windows 11 24H2 ARM64 and Windows Server 2025 specifically — signing
    isn't claimed to be frictionless on every SKU.
  - **ge9/IddSampleDriver** — the original sample VDD most forks build on.
    MIT/CC0, explicitly a sample/development driver, not documented as
    production-signed. Weaker bundling candidate than the above.
  - **nomi-san/parsec-vdd** (Parsec's own IddCx driver) — the driver itself is
    reportedly SignPath-signed, but the companion GUI app is reportedly
    unsigned and has been flagged by AV/SmartScreen — less clean to bundle.
  - License compatibility: MIT and CC0/public-domain are both compatible with
    this project's GPL-3.0 for bundling/redistribution, so licensing isn't the
    blocker for the two MIT candidates above — the blocker is the added
    maintenance surface of vendoring a *driver* plus residual signing friction
    on some Windows SKUs.
- Once a virtual monitor exists, the app side is comparatively simple: it
  already enumerates monitors generically (`monitors.py`) and already sends
  `-monitor <output>` to doubletake — a virtual display would just show up as
  another entry.

## Other no-driver options considered, and why they don't help either

Checked in case they sidestepped the signing problem entirely. None do, at least not
on the machine this was built against:

- **RDP's built-in virtual display.** A Remote Desktop session gets a driver-free virtual
  monitor for the length of the session — but it needs an inbound RDP *host*, which
  **Windows 11 Home does not support** (confirmed on the dev machine: `Microsoft Windows
  11 Home`). Looping RDP into the same machine to farm a virtual display would also hijack
  the console session rather than add a second desktop alongside it, so this would be a
  non-starter even on Pro/Enterprise.
- **GPU-vendor virtual outputs.** NVIDIA and AMD both have indirect/virtual display
  features in some driver stacks, but they target datacenter/vGPU deployments, not
  consumer cards. Confirmed not exposed on the dev machine's GPUs (`NVIDIA GeForce RTX
  4060 Laptop GPU`, `Intel UHD Graphics` — no virtual-display toggle in either driver).
- **A physical EDID-emulator "dummy plug."** The one path that's genuinely no-driver and
  no-admin: a cheap HDMI/DisplayPort dongle that fakes a monitor's EDID so Windows treats
  an unused video output as a real connected display. It's hardware, not something this
  app can provide, so implementing it is out of scope — but it's worth recording because
  it needs **zero code changes**. Once plugged in, Windows enumerates it like any other
  monitor, `monitors.list_monitors()` already picks up everything Qt sees, and today's
  "duplicate" flow already lets you cast that phantom monitor to the TV. That gets a user
  most of the way to "extend" — new desktop space, draggable windows, cast to the TV —
  with the app doing nothing new. Worth pointing a determined user at, no engineering
  required.

## Current behavior

The tray picker offers **"Cast duplicate of current display"** and **"Cast as
additional display"**. The latter uses the detection/enable/position/cast
implementation in `virtual_display.py` and `tray.py`. This describes the code
path, not a confirmed live extended-display result:

1. Not installed → a status message links the official upstream driver releases.
   Install separately following upstream instructions, then restart ScreenMagnet;
   the app and its setup do not install the driver for you.
2. Installed, disabled → self-elevates once to turn it on (one UAC prompt, expected to
   happen at most once per machine — see above), then falls through to step 3.
3. Enabled → positions it left/right of the primary per the existing `extend_side`
   config (already wired, unchanged), re-runs `monitors.list_monitors()` to pick it up,
   and casts to it exactly like "duplicate" mode casts to a real monitor — no changes
   needed in `caster.py`/`doubletake` at all, confirming the "app side is comparatively
   simple" assumption above.

The full sequence remains unverified against a real installed driver and
receiver. Historical absent-driver checks do not validate the installed/disabled
or enabled branches. Test the current source-built preview on actual Windows
hardware before claiming successful extended display, monitor selection, or audio.
