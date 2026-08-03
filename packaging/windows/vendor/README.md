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
