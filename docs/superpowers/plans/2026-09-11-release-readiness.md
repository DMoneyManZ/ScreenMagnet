# ScreenMagnet release readiness implementation plan

> For agentic workers: use superpowers:executing-plans or subagent-driven-development; coordinate file ownership and verify actual artifacts.

**Goal:** Prepare verified Windows setup and Linux AppImage downloads for a public preview review, keeping this repository private until publication is explicitly approved.
**Architecture:** Preserve the Qt tray application and pinned patched Go sender. Repair installed runtime resolution, build the sender from matching source, stage dependency notices/sources, and exercise frozen packages in native CI. Keep capture dependencies external on Linux; Windows setup obtains official runtime prerequisites with explicit setup text.
**Tech Stack:** Python 3.13, PySide6 Essentials 6.11.1, zeroconf 0.150.0, PyInstaller 6.22.2, Go 1.26, Inno Setup, AppImage.
**Spec:** User requested ScreenMagnet Windows EXE/setup and Linux release readiness like ProjectScope; ProjectScope AppImage question is read-only compatibility assessment.

## Global constraints

- Preserve GPL-3.0-or-later; do not publish the private repository or push a public release tag during readiness work.
- Do not cast to a TV or record real screens as a packaging test. Use offline widgets and synthetic GStreamer pipelines.
- Do not package credentials, local configuration, logs, LoRA data, or the old unreproducible sender binary.
- Ubuntu 22.04 is the Linux build baseline. Ubuntu 24.04 runtime verification remains required; KDE/SteamOS/Wayland casting needs real receiver testing.

## Tasks

- [ ] Runtime repair: regression tests for frozen Windows sender lookup and GStreamer path setup; resolve sibling sender without registry environment changes, keep writable pairing state outside Program Files, and handle missing sender launch visibly.
- [ ] Windows package: build the patched sender from pinned source, match setup version0.84, provide explicit official prerequisite downloads, run frozen self-test and installed/uninstalled smoke checks; use an upstream link for optional VDD rather than an absent bundled ZIP.
- [ ] License/source payload: stage allowlisted application source, patched Go source with vendored dependencies, exact Qt/PySide/zeroconf sources and license texts. Both package formats include the staged payload.
- [ ] Linux package: verify existing artifact, add missing source/notices, add a per-user installation path for the downloaded AppImage plus desktop icon and clear capture-dependency setup.
- [ ] CI delivery: run native Windows and Ubuntu packaging checks; use draft release assets because Actions artifact quota was reached in this account. Keep packages reviewable and private.
- [ ] Release review: inspect hashes and package inventories, document actual test evidence and remaining receiver/hardware checks, and report ProjectScope's existing .run-only/GNOME50 limitation.
