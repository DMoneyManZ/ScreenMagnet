# Prebuilt doubletake.exe

`doubletake.exe` here is checked in as a prebuilt binary, breaking from the rest of the
project's "not vendored, rebuild from `patches/`" convention (see the top-level `.gitignore`
and `spike/build-doubletake.sh`).

Why: the Windows capture backend (`d3d11screencapturesrc` / DXGI Desktop Duplication) lives in
two source files, `capture_windows.go` and part of `capture_unix.go`, that were never captured
into `patches/0001-screenmagnet-fixes.patch` before this binary was built. Without that source,
CI has no way to reproduce this exact binary from scratch. It's been confirmed working —
casts real video to a real AirPlay TV — but currently lacks audio on Windows (`doubletake`'s
audio capture only has a Linux/PulseAudio/PipeWire backend; see the README's
"Known limitations").

Follow-up needed: reconstruct `capture_windows.go` from scratch (it can't be safely
reverse-engineered from the binary in reasonable time) and fold it into the patch, at which
point this binary should be rebuilt reproducibly by CI instead of checked in here.

## 2026-08-03: reconstructed build exists, not yet swapped in

`capture_windows.go` has been reconstructed (best-effort — see the diff in
`patches/0001-screenmagnet-fixes.patch`, which now includes it, and the WASAPI2/WASAPI
loopback audio branch in `audio.go`) and `GOOS=windows GOARCH=amd64 go build ./cmd/doubletake`
succeeds cleanly (build-only; `go vet` clean too). **This checked-in `doubletake.exe` has
deliberately NOT been replaced.** It is confirmed-working on a real AirPlay TV (video-only);
the new build is not yet verified against real hardware — it has not been run at all, only
compiled — and adds two things that were reconstructed rather than recovered:

- The `d3d11screencapturesrc` capture pipeline is a plausible-but-unverified reconstruction
  based on inspecting the actual GStreamer elements/properties installed on the dev machine
  (`gst-inspect-1.0 d3d11screencapturesrc`, `d3d11convert`, `d3d11download`, `tcpclientsink`,
  etc.), not recovered source. Pipeline shape (element choice, format negotiation) is inferred
  from those properties plus the existing X11/Wayland pipelines in `capture.go`, not tested.
- The device-path → `monitor-index` mapping (`\\.\DISPLAY1` → `0`) for multi-monitor `-monitor`
  selection is an explicitly-flagged assumption in `capture_windows.go`'s doc comment — untested
  on a real multi-monitor rig, may not hold.
- WASAPI2/WASAPI loopback audio capture (`audio.go`) is likewise unverified end-to-end on
  Windows.

Recommended rollout: ship this as an opt-in "audio (beta)" / "Windows capture (beta)" build
alongside the known-good exe rather than replacing it outright — e.g. a second binary or a
`-beta` flag in the launcher — until someone runs it against a real Apple TV / AirPlay receiver
and confirms video still works and audio actually plays in sync. Only then should this file be
rebuilt reproducibly by CI and the checked-in exe here retired.

## `VirtualDisplayDriver-installer.zip`

Downloaded from `https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VDD.Control.25.7.23.zip`
(71,225,903 bytes, SHA-256 `a701f2272e9fcf382849b24f913c6dd07597b3b1116525f2e90182f019609154`).
It's a `.zip`, not an `.exe`/`.msi` — the upstream project ships a portable, self-elevating
"VDD Control" app inside the archive rather than a classic installer binary; nothing
mislabeled here. `app/screenmagnet/virtual_display.py` now points users at this exact file
(`INSTALLER_ZIP`) when the driver isn't installed yet. Unzip it and run `VDD Control.exe`
once (admin, one UAC click) to install/enable the driver; see docs/EXTENDED-DISPLAY.md for
the full detection/enable/position implementation this feeds into.
