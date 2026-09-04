# ScreenMagnet Linux release and verification guide

## Release position

Linux support is released in stages:

1. Ubuntu 22.04 and Ubuntu 24.04 are the required release gates.
2. SteamOS/Steam Deck is confirmed after the Ubuntu artifact passes.
3. Other glibc-based x86_64 distributions are supported on a best-effort basis.

The current AppImage is x86_64 and glibc-based. It is not a universal promise
for ARM Linux, Alpine/musl, every window manager, or every GStreamer plugin set.
Those targets need separate artifacts or explicit test results.

## Dependency model

ScreenMagnet has three deliberately separate layers. The launcher also installs
the small EGL/XCB set PySide6 needs on a minimal desktop; that was the missing
system-library class that could look like a Python 3.14 package failure.

| Layer | Delivery | Host requirement |
|---|---|---|
| Tray application | Python 3.13, PySide6 and zeroconf frozen by PyInstaller | None for AppImage users |
| AirPlay sender | Patched, statically built `doubletake` inside the AppImage | None for the sender binary |
| Screen/audio capture | GStreamer, PipeWire/PulseAudio, portal or X11 integration | Native packages or the SteamOS distrobox |

Do not copy Python 3.13 packages into a different system interpreter. Native
extension modules are tied to a Python ABI and platform. The supported models
are either a managed 3.13/3.14 virtual environment or a frozen AppImage that
carries its own interpreter.

Python 3.13 remains the official artifact-build baseline for reproducibility.
Python 3.14 is an independently tested source/build input. PySide6 6.11.1 and
PyInstaller 6.22.2 both publish compatible packages for it.

## One launcher

Run every Linux workflow through the repository-root launcher:

```bash
bash ./screenmagnet-linux.sh doctor
bash ./screenmagnet-linux.sh run
```

Available operations:

```bash
bash ./screenmagnet-linux.sh install-deps      # Ubuntu/Debian/Fedora/Arch native packages
bash ./screenmagnet-linux.sh setup-source      # isolated Python venv + patched doubletake
bash ./screenmagnet-linux.sh run-source
bash ./screenmagnet-linux.sh run-appimage
bash ./screenmagnet-linux.sh setup-steamos     # creates the screenmagnet distrobox
bash ./screenmagnet-linux.sh build-appimage
bash ./screenmagnet-linux.sh test
```

The launcher does not modify the operating system during `run`, `doctor`, or
`test`. `install-deps` is the only path that invokes the native package manager
with `sudo`. On SteamOS it refuses to alter the read-only base system and routes
capture dependencies into distrobox instead.

When the FUSE 2 library or a usable `/dev/fuse` device is missing,
`run-appimage` automatically sets
`APPIMAGE_EXTRACT_AND_RUN=1`. This is slower to start but does not require root.
The AppImage copies its bundled `doubletake` binary into the user's shared data
directory so the SteamOS distrobox can see and execute it.

## Available repair strategies

### A. Frozen AppImage — release default

Use this for normal users. Python and Python packages are bundled. The host
still needs a working screen-capture route: native GStreamer or the prepared
distrobox.

```bash
bash ./screenmagnet-linux.sh build-appimage
bash ./screenmagnet-linux.sh run-appimage
```

### B. Managed source environment — development and recovery

Use this for debugging or when AppImage compatibility is uncertain. The
launcher selects Python 3.13/3.14, creates a venv under
`~/.local/share/screenmagnet`, installs the project there, and builds the pinned
sender into the same data tree.

```bash
bash ./screenmagnet-linux.sh setup-source
bash ./screenmagnet-linux.sh run-source
```

### C. Native GStreamer — Ubuntu first

This gives the simplest runtime and should be the first Ubuntu test path:

```bash
bash ./screenmagnet-linux.sh install-deps
bash ./screenmagnet-linux.sh doctor
```

The doctor must report both `gst-launch-1.0` and at least one working H.264
encoder (`x264enc`, `openh264enc`, `vah264enc`, or `vaapih264enc`). Merely
registering a hardware encoder is not enough; the real cast test confirms that
the installed GPU can initialize it.

### D. SteamOS distrobox fallback

Do not unlock or modify the SteamOS root filesystem for this application.

```bash
bash ./screenmagnet-linux.sh setup-steamos
bash ./screenmagnet-linux.sh doctor
bash ./screenmagnet-linux.sh run
```

If an existing `screenmagnet` distrobox already works, keep it. The setup
command is idempotent and will not replace it.

## Automated verification

GitHub Actions must complete these gates before a tag is created:

1. Install the project under clean Python 3.13 and 3.14 environments.
2. Run `app/tests/ci_smoke_test.py` with Qt's offscreen backend.
3. Build the pinned `doubletake` revision and apply the project patch.
4. Build the AppImage without requiring FUSE on the build runner.
5. Extract the AppImage and verify its AppRun, frozen application, sender,
   desktop entry, icon, and required sender flags.
6. Reject unresolved `@EXEC@` or `@WORKDIR@` desktop-template tokens.
7. Execute the finished AppImage's `--self-test` through extract-and-run.
8. Validate the SHA-256 checksum and upload both files as CI artifacts.

Local equivalent:

```bash
bash ./screenmagnet-linux.sh build-appimage
bash ./packaging/linux/verify-appimage.sh \
  packaging/linux/dist/ScreenMagnet-x86_64.AppImage
```

These checks prove package structure and frozen-runtime startup. They do not
pretend to prove a real capture, network discovery, receiver pairing, or audio.

### Test the downloaded CI artifact

Download both files from the `ScreenMagnet-linux-ci` Actions artifact into one
directory. From that directory, run:

```bash
sha256sum --check ScreenMagnet-x86_64.AppImage.sha256
export SCREENMAGNET_APPIMAGE="$PWD/ScreenMagnet-x86_64.AppImage"
bash /path/to/ScreenMagnet/screenmagnet-linux.sh doctor
bash /path/to/ScreenMagnet/screenmagnet-linux.sh run-appimage
APPIMAGE_EXTRACT_AND_RUN=1 \
  bash /path/to/ScreenMagnet/screenmagnet-linux.sh run-appimage
```

The first launch exercises normal FUSE mounting when both `libfuse.so.2` and a
usable `/dev/fuse` are present. The second explicitly exercises extraction.
If the first launch also extracts, `doctor` will say why; record that as a FUSE
environment result rather than an application failure.

### Reproduce the Python 3.14 source check

This keeps 3.14 isolated and never changes the distribution Python:

```bash
uv python install 3.14
export PYTHON="$(uv python find 3.14)"
export SCREENMAGNET_VENV="$HOME/.local/share/screenmagnet/venv-314"
bash ./screenmagnet-linux.sh setup-source
QT_QPA_PLATFORM=offscreen bash ./screenmagnet-linux.sh test
bash ./screenmagnet-linux.sh run-source
```

Repeat with `3.13`/`venv-313` when comparing the two interpreters. If both fail
while importing Qt with a missing `.so` library, run `install-deps`; do not copy
3.13 `site-packages` into the 3.14 environment.

## Manual Ubuntu release gates

Perform the following against the downloaded CI artifact, not a locally rebuilt
copy. Record the OS version, desktop/session type, GPU, receiver, artifact
SHA-256, and result.

### Ubuntu 22.04

- Run `bash screenmagnet-linux.sh doctor`.
- Launch normally with FUSE 2 installed.
- Launch with `APPIMAGE_EXTRACT_AND_RUN=1` to prove the fallback.
- Confirm the application icon, tray icon, popup and settings window.
- Discover a real AirPlay receiver.
- Pair when a PIN is requested.
- Cast video for at least five minutes.
- Confirm audio, stop, restart and reconnect.
- Test primary and secondary monitor selection under Xorg.

### Ubuntu 24.04

- Repeat every 22.04 check.
- Test the default GNOME Wayland session.
- Test an Xorg session when available.
- Verify portal/PipeWire capture under Wayland.
- Verify normal AppImage execution with `libfuse2t64` and fallback execution
  with it absent.

## Manual SteamOS gate

- Use the same CI AppImage and checksum tested on Ubuntu.
- Run from Gaming Mode and Desktop Mode where practical.
- Confirm the existing native dependencies or `screenmagnet` distrobox.
- Confirm that `~/.local/share/screenmagnet/runtime/doubletake/bin/doubletake`
  is created from the AppImage payload.
- Confirm the container can see that exact path.
- Discover, pair and cast for at least five minutes.
- Confirm audio, Deck display capture, external-monitor selection, stop and
  reconnect.
- Reboot the Deck and repeat launch/cast to prove persistence.

## Other-distribution qualification

Use the Ubuntu artifact unchanged. Run `doctor`, the AppImage verifier, and the
same real-cast sequence. Prioritize current Fedora, Arch, Debian and Linux Mint.
A distribution is listed as confirmed only after its exact version and desktop
session pass. Alpine/musl and ARM require separate engineering work and must not
be labeled supported based only on an x86_64 glibc AppImage.

## Failure record

For each failure, capture:

```text
Distribution/version:
Kernel:
Desktop/session (Wayland or Xorg):
GPU/driver:
Receiver/model:
Artifact SHA-256:
Launcher command:
Doctor output:
Observed result:
Relevant terminal output:
```

Never include pairing PINs, credentials, or private network identifiers in a
public issue.

## Tagging gate

Do not create a release tag until all of the following are true:

- Linux packaging CI is green at the exact commit to be tagged.
- Ubuntu 22.04 and 24.04 manual gates pass.
- SteamOS passes or is explicitly documented as pending for a pre-release.
- `app/screenmagnet/__init__.py`, `pyproject.toml`, changelog and intended tag
  report the same version.
- The release workflow has `contents: write` only on the publishing job.
- The AppImage and `.sha256` files have been downloaded and verified once.

After those gates pass, create a release-candidate tag first. Promote to the
official release only after installing and casting from the release-candidate
asset itself.
