# ScreenMagnet preview release results — 2026-09-11

## Verified candidate

- Build commit: `c6495c67ea5c6fbe6cb366088b05704a17fa85f1`.
- [Complete native packaging run](https://github.com/DMoneyManZ/ScreenMagnet/actions/runs/34571143653): prepare, Windows, Ubuntu 22 build and Ubuntu 24 downloaded-runtime jobs all passed.
- [Source compatibility run](https://github.com/DMoneyManZ/ScreenMagnet/actions/runs/34571221006): Python 3.13 and 3.14 passed.
- [Private candidate downloads](https://github.com/DMoneyManZ/ScreenMagnet/releases/tag/untagged-de23463ab0ce34d3ae9d).
- [Implementation PR](https://github.com/DMoneyManZ/ScreenMagnet/pull/2), based on the existing Linux-support branch.
- Local downloads: `/home/duncan-murphy/Downloads/ScreenMagnet-0.84-Preview`.

Windows setup and portable ZIP were built from matching sender source. Native Qt
startup, prerequisite/plugin checks, synthetic H.264 encoding, installed startup,
uninstall and retained user-state checks passed on Windows Server 2022 CI.
The rebuilt Windows sender has not been validated against a real receiver.

The AppImage passed structure, checksum, matching source-companion, startup and
synthetic H.264 checks on Ubuntu 22.04 and 24.04. The downloaded artifact also
passed startup/encoding on this Ubuntu 26.04.1 desktop in isolated user-data paths.
Tests used synthetic frames and a fake sink, without live screen capture or casting.

The clean public source export passed 53 local test cases (49 executed, four
PowerShell-only tests skipped). Native Windows CI executed the PowerShell tests;
Linux-specific executable tests are appropriately skipped on Windows. Relative
documentation links and a limited credential-pattern scan of the export passed.
This is not a claim of a comprehensive forensic secret audit of private history.

## Artifact integrity

All five downloaded artifact SHA-256 files matched their contents:

| Artifact | SHA-256 |
|---|---|
| Windows setup | `fb8d8a02ab5e107c1773e7823b82c435b79d1bda77496c4520caffc22a26407e` |
| Windows portable ZIP | `572ffd5873b8b5ec218f4dcaa47719110ac1c99fed867d31dc25be91421689e4` |
| Linux AppImage | `0d164160d2b4b11e2ee331fb682cb616ca0e2c5c042c38cb3cc5cada323992ed` |
| Linux corresponding sources | `af61553487a8b398fff40bb1e86b84d0b528e5afa96924b1755ff62fdd8ac11a` |
| Clean application source export | `70ff1030edb904435ff3f31e1cdfa6a35bf4fe58606e45ec36722a08b4542709` |

The AppImage is approximately 78 MB; its separate source companion is 411 MB.
Windows setup is approximately 111 MB; its portable ZIP is 127 MB. Original
notices remain in the application. The Linux AppImage embeds its source archive's
hash; the actual companion was checked against it. Windows ZIP inspection
confirmed the rebuilt sender and source archives, with no VDD installer archive.

The distributed sender archive is rebuilt during staging. Its credentials-handling
Go implementation files are included; actual credentials/data files remain excluded.
Fresh Linux source staging excludes generated virtual environments and frozen output.

## Publication decision

The original ScreenMagnet repository and candidate release remain **private/draft**.
No public visibility change, history rewrite, receiver cast, driver installation,
dataset collection, or training was performed.

The existing repository cannot simply be made public as reviewed:

1. Historical `packaging/windows/vendor/doubletake.exe` explicitly lacks the exact
   modified source used to build it. The reconstructed sender is distinct.
2. Historical VDD ZIP contains no license/notice files and includes additional
   binaries such as `devcon.exe`; upstream project licensing does not by itself
   establish complete distribution coverage for that archive.

A clean application source export with no historical binaries or Git history is
prepared and attached to the private candidate. Use that export for a new public
repository/publication path while retaining the existing private history. Do not
publish the legacy binary archives merely because new packages exclude them.

Public **preview** wording must retain the pending real receiver pairing/video/audio,
multi-monitor/virtual-display and SteamOS/Bazzite tests. Stable-release readiness
has not been established by synthetic packaging checks. Other Linux desktops and
distributions are best-effort until tested.

The official optional PayPal recipient `demurphy242@gmail.com` is present in the
settings UI, README, installation guide and GitHub funding configuration.
ScreenMagnet retains GPL-3.0-or-later.

## ProjectScope Linux answer

ProjectScope's public v1.0.0 Linux release has a `.run` Python-zipapp installer,
source archive and checksums, **not an AppImage**. Its overlay requires GNOME
Shell 50 on Wayland. SteamOS/KDE and Gamescope are unsupported by that backend;
wrapping it in an AppImage would not add them. Fedora/Arch/Bazzite compatibility
depends on using the required GNOME session and dependencies, and is unverified.
