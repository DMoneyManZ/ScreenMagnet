# ScreenMagnet — Research Findings (2026-08-01)

Two research agents (protocol + app-shell) plus on-box verification. Everything below
is measured on the Legion, not assumed.

## TL;DR

**Build against Miracast-over-Infrastructure (MICE) targeting the two Roku TVs.**
Wi-Fi Direct is impossible on this kernel; MICE doesn't need it.

---

## 1. Wi-Fi Direct / Miracast P2P is DEAD on this box (kernel-level)

`iw list` reports `P2P-client` and `P2P-GO` — but **`P2P-device` is absent**, and that
is the interface type both wpa_supplicant and iwd must create to run P2P.

Root cause pinned to a commit:

| Kernel | `NL80211_IFTYPE_P2P_DEVICE` in `mt76/mt792x_core.c` |
|---|---|
| 6.11 – 6.13 | absent |
| **6.14** | **first release with support** (commit `5a569e90162a`) |

This box runs `6.11.11-valve29-1-neptune` — three releases short.

**The iwd-vs-wpa_supplicant question is a red herring.** Switching backends changes
nothing while the kernel refuses to create the P2P netdev. (For the record: iwd 3.0 here
*does* ship full P2P + Wi-Fi Display D-Bus interfaces, and NetworkManager 1.50.1 supports
P2P on the iwd backend since NM 1.36 — so the tooling was never the problem.)

Revisit only if SteamOS ships kernel ≥ 6.14.

## 2. What is actually on the LAN (measured via in-process mDNS/SSDP)

`avahi-daemon` is **inactive**, which is why the first sweep found nothing. Querying
sockets directly:

Addresses below use the RFC 5737 documentation range in place of the real ones.

| Host | Device | AirPlay | **MICE** (`_display._tcp`) | DLNA |
|---|---|---|---|---|
| 192.0.2.10 | **43" TCL Roku TV** | ✅ | **✅** | ✅ |
| 192.0.2.11 | **65" Element Roku TV** | ✅ | **✅** | ✅ |
| 192.0.2.12 | Samsung 7 Series (58") | ✅ | — | ✅ |
| 192.0.2.13 | LG WebOS TV (~2018) | — | — | ✅ |
| 192.0.2.14 | Roku Express | ✅ | — | ✅ |
| 192.0.2.15 | Denon AVR-X3500H | ✅ (audio) | — | ✅ |
| 192.0.2.16 / .17 | iMac / MacBook Pro | ✅ | — | — |

- **`_googlecast._tcp`: zero responders.** No Chromecast exists here — the entire Google
  Cast path is academic.
- **No Apple TV answered** (asleep/off). Re-probe with it awake.

The two Rokus advertising `_display._tcp` is the key discovery: that is Miracast running
over the ordinary LAN, requiring no Wi-Fi Direct at all.

## 3. Protocol verdicts

| # | Protocol | Verdict | Targets |
|---|---|---|---|
| 1 | **MICE via `org.gnome.NetworkDisplays`** | **WORKS** — no P2P, no backend change | 2 Rokus |
| 2 | **AirPlay via `doubletake`** | **FLAKY** — real but 3-month-old alpha | 7 |
| 3 | DLNA file playback | works for *files*, dead for mirroring | 4 renderers |
| 4 | Google Cast via GND | 1–13 s latency, and no device exists | **0** |
| 5 | Miracast P2P | **DEAD** until kernel ≥ 6.14 | n/a |

**MICE details:** `flatpak install flathub org.gnome.NetworkDisplays` (v0.99.0, Jan 2026,
actively committed through Jul 2026). Sink RTSP endpoint port **7236**. Release notes for
0.99.0: *"Fixed WFD keep-alive and RTCP port handling for Roku/Hisense devices"* — fixed
for exactly our hardware, one release ago. Latency ~150–400 ms.

**AirPlay details:** `omarroth/doubletake` (Go, LGPL-3.0+, created 2026-04-04). Full
AirPlay 2 sender: SRP-6a PIN pairing with credential persistence, FairPlay, ChaCha20
stream encryption, X11 + Wayland capture, daemon mode, KDE Plasma widget. Confirmed
working against Apple TV 4K 3rd gen. **Author states most code was LLM-written and
recommends against production use.** Open issues include "mirroring only sends one frame".

`pyatv` is **not** an option — client/remote library, audio (RAOP) only, no mirroring.

## 4. ⚠ There is no H.264 encoder on this system

Verified on-box:

```
x264enc ABSENT · openh264enc ABSENT · vah264enc ABSENT · vaapih264enc ABSENT
vp8enc PRESENT · ximagesrc PRESENT · pipewiresrc PRESENT
```

The Mesa `radeonsi_drv_video.so` VA-API driver *is* installed — the Phoenix1 VCN silicon
can encode. GStreamer simply has no plugin to reach it. And `steamos-readonly status` =
**enabled**, so `pacman -S` is not available without disabling the read-only root (which
OS updates clobber).

**Consequences:**
- **GND-as-Flatpak sidesteps this entirely** — its manifest bundles `openh264`,
  `gst-plugins-ugly`, `gst-rtsp-server` inside the GNOME runtime. Strong reason to prefer
  Flatpak over a host build.
- **`doubletake` uses *host* GStreamer** → it will not find an H.264 encoder as things
  stand. Budget for running it in a distrobox with X11 socket + `/dev/dri` passed through.
- Any design assuming host GStreamer can encode H.264 is **wrong today**.

## 5. App shell (verified separately)

Session is **X11** (`XDG_SESSION_TYPE=x11`), which is lucky:

- Capture is plain GStreamer `ximagesrc` — no portal permission dialog per launch.
- Avoids **KDE bug 476602** (open, unresolved): `pipewiresrc` from the XDG screencast
  portal produces a **black screen** on Wayland.
- `QSystemTrayIcon.geometry()` returns a **valid rect on X11** (empty on Wayland), so the
  tray popup can be a custom frameless `Qt.Popup` widget instead of a stock `QMenu`.

Tray notes: Qt6 speaks StatusNotifierItem natively on Plasma 6. Ship a `.desktop` file +
`QApplication.setDesktopFileName()`, use `QIcon.fromTheme()`, and set
`setQuitOnLastWindowClosed(False)`.

Gate popup positioning behind `QGuiApplication.platformName() == "xcb"` with a `QMenu`
fallback, so a future Wayland switch degrades instead of breaking.

## 6. Integration path — do not reimplement Miracast

GND 0.98+ ships a headless D-Bus daemon: **`org.gnome.NetworkDisplays.Manager`**

- Property `Displays` — `aa{sv}` with `display-name`, `priority`, `state`, `protocol`
- `StartStream(s sink_uuid) → (s stream_unit_name)`
- `StopStream(s stream_unit_name)`
- States: `disconnected`, `ensure-firewall`, `wait-p2p`, `wait-socket`, `wait-streaming`,
  `streaming`, `error`

The PySide6 layer becomes: watch `Displays` → list sinks → `StartStream`/`StopStream`,
plus a NetworkManager secret-agent dialog for the WPS PIN.

⚠ **UNVERIFIED:** that the Flatpak actually exposes this daemon on the session bus. May
need a host build or a `--talk-name` addition. **Check this before designing around it.**

## 7. Pairing

- **Miracast (incl. MICE)** uses WPS. GND contains no WPS code — it delegates to
  NetworkManager via `NMSettingWifiP2P`. NM 1.50+ exposes `wifi-p2p.wps-pin`,
  `wps-pin-flags`, `wps-method` (`pbc`/`pin`/`pin-display`). iwd supports keypad +
  push-button only, **not** `pin-display`. Register an NM secret agent and answer the
  `wifi-p2p.wps-pin` request with a PySide6 dialog.
- **AirPlay** uses SRP-6a with a PIN shown on the TV, then persists credentials —
  one-time prompt per sink. `doubletake` implements this.
- **Cast / DLNA:** no pairing.

## 8. Biggest risk

> Everything rests on MICE completing an RTSP session with the two Roku TVs, and there is
> no fallback if it doesn't.

The P2P escape hatch is welded shut by the kernel. If the Rokus advertise `_display._tcp`
but refuse or drop the RTSP/RTP session (MICE was validated upstream mostly against LG
WebOS; Roku support is one release old), the Miracast branch is dead on arrival — leaving
only a three-month-old alpha AirPlay implementation that also can't find an H.264 encoder
without containerisation.

## 9. De-risk order — before writing app code

1. `sudo systemctl enable --now avahi-daemon`  *(needs the user's password; persists via
   the writable `/etc` overlay, no `steamos-readonly disable` needed)*
2. `flatpak install flathub org.gnome.NetworkDisplays`
3. Put the 43" TCL Roku on its screen-mirroring screen; run GND with
   `G_MESSAGES_DEBUG=all` and confirm a sink appears **and a picture actually lands**.
   **This single test decides the architecture.**
4. In parallel: build `doubletake` in a distrobox, point it at the Samsung
   (the Samsung, 192.0.2.12) and the Apple TV once awake.

---

## 10. HARD CONSTRAINT (user directive, 2026-08-01)

**ONLY stream to the development LG 43UK6090PUA**, identified by its mDNS instance name.
Resolve it by name, never by address — it was 192.0.2.20 on Wi-Fi and moved to 192.0.2.21
when it was wired, because the Ethernet NIC has a different MAC and so gets a different
DHCP lease. This is why discovery resolves targets by mDNS name rather than caching an
address.

Never target the other receivers on the LAN: they are in other rooms and in use.
Discovery may list them; streaming during development was hard-scoped to the one TV.

### Why the LG is AirPlay-only (tested, not assumed)
With **Screen Share open on the TV**, it still advertised NO `_display._tcp` and kept
7236/7250 **closed**. LG's Screen Share is **Wi-Fi Direct Miracast**, which kernel 6.11's
mt76 driver cannot do (no `P2P_DEVICE`). GND/MICE is therefore a dead end for this TV.

Its AirPlay 2 receiver, however, is live and needs nothing enabled:
`model=43UK6090PUA  srcvers=377.25.06  flags=0x644  features=0x7F8AD0,0x38BCB46`
plus `_hap._tcp` (HomeKit). Port 7000 open.

### Verified GND facts (kept for reference even though unused for the LG)
- D-Bus API confirmed working from outside the sandbox:
  `/org/gnome/NetworkDisplays/Manager` → `StartStream(s)→s`, `StopStream(s)`, `Displays aa{sv}`
- The Flatpak needs `flatpak override --user --talk-name=org.freedesktop.systemd1` or
  StartStream fails with `Unable to spawn nd-stream with StartTransientUnit: none`.
- **Sink UUIDs regenerate on every daemon restart** — never persist them; re-resolve by name.
