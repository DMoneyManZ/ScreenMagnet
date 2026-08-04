# "Cast as additional display" — feasibility

## Status: implemented against a real driver candidate, but untested against an actually-installed driver

No admin rights were available in the session that wrote this code, so the driver has
never actually been installed on this machine.

`app/screenmagnet/virtual_display.py` now drives the
**VirtualDrivers/Virtual-Display-Driver** project (MIT, github.com/VirtualDrivers/
Virtual-Display-Driver — see "What a real implementation needs" below for how it was
picked). A copy of its portable installer app is vendored at
`packaging/windows/vendor/VirtualDisplayDriver-installer.zip` (71,225,903 bytes,
SHA-256 `a701f2272e9fcf382849b24f913c6dd07597b3b1116525f2e90182f019609154` — verified
zip, not an `.exe`/`.msi`: the upstream project ships a portable app inside a zip, not a
classic installer; see that folder's README for the download provenance). Extracting it
and running `VDD Control.exe` once — self-elevating, one UAC click — installs the
signed driver. **This one step has not been performed in any session so far**, so
nothing below has been exercised against a real enumerated device.

### What's real vs. what's still just reasoned-through

Real, and confirmed working on this dev machine right now (no admin, driver absent):

- `is_installed()` / `is_enabled_now()` — query Windows for the driver's PnP adapter
  device (`Get-PnpDevice`, matching the friendly name `"Virtual Display Driver"` /
  `"IddSampleDriver Device HDR"` or instance ID prefix `ROOT\MttVDD`, exactly as the
  upstream project's own scripts do it). Read-only, no admin, and **confirmed
  gracefully returns `False`/`False`** on this machine where the driver genuinely isn't
  installed — verified by actually running it, not just by reading the code.
- `find_virtual_display_name()` — enumerates real display adapters via
  `EnumDisplayDevicesW` (ctypes) looking for a monitor sub-device carrying the
  `MTT1337` spoofed-EDID marker. **Confirmed to run cleanly against this machine's real
  adapters** (an RTX 4060 laptop GPU + Intel UHD Graphics) without crashing and without
  a false match — meaningful evidence the ctypes `DISPLAY_DEVICEW`/`DEVMODEW` struct
  layouts are laid out correctly for the real Win32 ABI, even though there's no virtual
  monitor here to find.

Implemented but genuinely unverified — no virtual monitor exists anywhere this was
tested to run it against:

- `enable_virtual_display(side)` / the internal `_enable_pnp_device_elevated()` — self
  -elevates via `Start-Process -Verb RunAs -Wait` (same idiom as the upstream project's
  `toggle-VDD.ps1`) to call `Enable-PnpDevice` on the adapter. The UAC round-trip itself
  — including "user clicks No" surfacing correctly as a clean failure rather than a
  hang or a crash — has never actually happened.
- `_position_virtual_display(side)` — places the virtual monitor left/right of the
  primary via the classic `EnumDisplayDevices`/`ChangeDisplaySettingsEx` + `DEVMODE
  .dmPosition` Win32 pair (ctypes), not the newer path-based CCD `SetDisplayConfig` API
  — chosen per the "Programmatic left/right positioning" research below. No admin
  needed (per-user display-settings change), best-effort (failure doesn't fail the
  whole cast), but unverified end-to-end.
- The `tray.py` wiring (`cast_to("extend")` → `_start_extend` → an off-GUI-thread
  `updater.CallWorker` running install-check → enable → position → re-enumerate →
  cast) has been read through carefully and syntax/import-checked, but **could not be
  exercised through Qt at all in this session** — no PySide6-capable Python environment
  was available here (the project pins Python 3.13, only 3.14 was on PATH). This is a
  second, independent kind of untested-ness from "the driver was never installed" —
  even the plumbing that calls into `virtual_display.py` has only been read, not run.

### Why installed/enabled/attached are three different questions, and what each means

- **Not installed** → `cast_to("extend")` shows a message pointing at the vendored zip
  above and explains the one manual step (extract, run `VDD Control.exe`, restart
  ScreenMagnet) — the app never launches the installer itself.
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
- Existing open-source building blocks exist that could be vendored the same
  way `doubletake.exe` already is — but that's a real dependency decision
  (licence check, provenance, ongoing maintenance of a *driver*, not just an
  app) that deserves its own pass, not a few lines bolted onto this feature.
  Candidates surveyed (not independently verified beyond this research pass —
  re-check before committing to one):
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

The tray picker offers **"Cast duplicate of current display"** (works today, unchanged)
and **"Cast as additional display"**, which now runs the real
install/enable/position/cast sequence in `virtual_display.py` + `tray.py` described
above instead of a blanket "not available" message:

1. Not installed → status message points at the vendored zip and the one manual step
   (extract, run `VDD Control.exe`, restart ScreenMagnet); the app never launches it
   for you.
2. Installed, disabled → self-elevates once to turn it on (one UAC prompt, expected to
   happen at most once per machine — see above), then falls through to step 3.
3. Enabled → positions it left/right of the primary per the existing `extend_side`
   config (already wired, unchanged), re-runs `monitors.list_monitors()` to pick it up,
   and casts to it exactly like "duplicate" mode casts to a real monitor — no changes
   needed in `caster.py`/`doubletake` at all, confirming the "app side is comparatively
   simple" assumption above.

None of steps 1–3 have been run against a real installed driver yet (see "What's real
vs. what's still just reasoned-through" above) — this session had no admin rights and
could not perform the one-time install. The next person with admin on a machine with
this driver installed is the one who can actually confirm the enable/position/cast path
end-to-end; until then, treat the "installed but disabled" and "enabled" branches as
best-effort, not verified.
