# Linux preview verification

[Installation](INSTALL.md) · [Project overview](../README.md)

**Ubuntu 22.04 and Ubuntu 24.04 on x86_64 are the release baseline.** The
AppImage targets glibc-based Linux. ARM, Alpine/musl, and other desktop or
GStreamer combinations need separate qualification.

The Linux package build and Ubuntu 24.04 downloaded-package checks succeeded in
[run 34569097416](https://github.com/DMoneyManZ/ScreenMagnet/actions/runs/34569097416)
at commit `32b0629`. This records that build's result. Later changes to exact
corresponding-source coverage and packaging are still being verified; the
historical pass does not establish that a newer commit passes.

**Live receiver discovery, pairing, video, and audio are not confirmed by these
package checks.** SteamOS/Steam Deck and Bazzite remain pending real-device and
receiver verification.

## Runtime and source requirements

| Component | Delivery | Additional requirement |
|---|---|---|
| Tray application | Python 3.13, PySide6, and zeroconf in the AppImage | Desktop graphics libraries |
| AirPlay sender | Patched `doubletake` binary in the AppImage | Reachable compatible receiver |
| Screen/audio capture | External GStreamer and desktop capture integration | Native packages or the prepared distrobox; usable H.264 encoder |

Release packaging uses **Python 3.13 only**. Python 3.14 is covered by the
separate source-compatibility tests, not the release build. AppImage users need
no host Python. Source users use an isolated 3.13/3.14 environment; never copy
one interpreter's `site-packages` into another or replace Ubuntu's system Python.

The Linux package layout is being changed to ship matching source archives as a
**companion download beside the AppImage**. This keeps the large source payload
out of routine extract-and-run startup. Keep the companion from the same build
and its checksum with the AppImage when retaining or redistributing a package.
It contains the application/build sources and dependency sources identified by
that build's manifest. Use the published asset names and manifest to identify the
matching files; do not substitute sources from a different release. Windows
packages keep their source payload bundled.

For a Linux rebuild, extract the application source, use Python 3.13, and follow
the included build scripts on Ubuntu 22.04 with `deb-src` repositories enabled.
The release workflow lists the exact build tools and packages. The source stager
uses apt/dpkg to retrieve source packages matching the libraries actually frozen;
an unidentified library or unavailable exact source version stops packaging.
The pinned sender source and project patch must
match the packaged binary. The companion/source-coverage changes require their
own successful build before they can be called verified.

## Two workflows

[Source compatibility](../.github/workflows/linux-ci.yml) runs on pull requests
or manual dispatch. It installs the project on Ubuntu 24.04 with Python 3.13 and
3.14, then runs the offscreen application smoke test and unit tests. This workflow
has read-only repository permissions and does not publish packages.

[Verified preview packages](../.github/workflows/release.yml) runs separately on
manual dispatch or version tags:

1. Check that application and project versions agree; create a draft prerelease,
   or validate that a supplied draft targets the exact build commit.
2. Build natively on Ubuntu 22.04 using Python 3.13 and the pinned Go sender
   revision plus project patch. Run the application and packaging-helper tests.
3. Stage matching source and license material, build the AppImage, and verify its
   executable, sender flags, desktop entry, icon, notices, checksum, and frozen
   startup through extract-and-run.
4. Upload the AppImage, checksum, installer helper, Linux launcher, existing SVG
   icon, installation guide, and generated companion files to the draft release.
5. On Ubuntu 24.04, download the actual draft AppImage, checksum, installer
   helper, and icon. Verify the package, install it into isolated user paths,
   validate the desktop entry, run the installed wrapper's self-test, uninstall,
   and confirm the user-state sentinel remains.

The Ubuntu 24.04 job also tests direct FUSE startup when `/dev/fuse` is readable
and writable. When the device is unavailable it records that limitation; the
extract-and-run check still runs. These are bounded offscreen checks, not a live
screen cast or a desktop-tray appearance test.

Packages are staged as **private draft-release assets**, not Actions artifacts.
This avoids relying on Actions artifact-storage quota. Authorized maintainers
review the downloads before publication; a green workflow does not publish the
draft automatically. The default token permission is `contents: read`.
Draft creation, package uploads, and the Ubuntu draft-download job explicitly
use `contents: write`, because accessing unpublished draft assets requires
repository push access. Source-only tests retain read-only permissions.

## Inspect the downloaded preview

Use an authenticated account with access to the draft. Select the exact draft
reported by the workflow, then download its assets through GitHub or `gh`:

```bash
DRAFT_TAG='<draft tag reported by the workflow>'
gh release download "$DRAFT_TAG" --repo DMoneyManZ/ScreenMagnet --dir preview
cd preview
sha256sum --check ScreenMagnet-x86_64.AppImage.sha256
```

Verify the matching source companion against its published checksum as well.
The installer needs `install-appimage.sh`, the AppImage and checksum, and
`screenmagnet.svg` together. Keep `screenmagnet-linux.sh` for dependency setup
and diagnosis. See [Installation](INSTALL.md) for the complete user flow.

On Ubuntu, prepare capture dependencies and install as your normal user:

```bash
bash ./screenmagnet-linux.sh install-deps
bash ./screenmagnet-linux.sh doctor
bash ./install-appimage.sh
```

Only dependency setup invokes the native package manager with `sudo`. The
AppImage installer verifies its input, writes user-owned files, and does not
launch the application or start a cast. Its installed wrapper always uses
extract-and-run, so FUSE is not required.

For an additional bounded check without casting:

```bash
QT_QPA_PLATFORM=offscreen \
  "${XDG_DATA_HOME:-$HOME/.local/share}/screenmagnet/screenmagnet" --self-test
```

`doctor` is read-only. Other launcher operations can prepare user files: source
setup creates the managed environment, source execution can prepare a missing
environment, and AppImage execution makes its sender available in user data.
Do not describe those operations as making no filesystem changes.

## Remaining live verification

Use the downloaded package at the commit being evaluated. Record the artifact
checksum, distribution/version, session type, GPU/driver, receiver, and result.

| Target | Required checks before claiming live support |
|---|---|
| Ubuntu 22.04 | Menu/tray/settings appearance; discovery and PIN pairing; at least five minutes of video with audio; stop/restart/reconnect; primary and secondary monitor selection under Xorg |
| Ubuntu 24.04 | Repeat Ubuntu checks in the default Wayland session and Xorg where available; confirm portal/PipeWire capture; check FUSE and extraction routes |
| SteamOS/Steam Deck | Desktop Mode and Gaming Mode where practical; container sees the shared sender; Deck/external monitor capture; receiver/audio checks; repeat after reboot |
| Bazzite | Its actual desktop/session and container route; receiver/audio checks, monitor selection, and persistence after reboot |

For SteamOS and Bazzite, use an existing supported distrobox/container engine and
run `bash ./screenmagnet-linux.sh setup-steamos`. Setup creates or reuses the
`screenmagnet` container, installs capture dependencies inside it, and checks
encoder availability. Keep the read-only/immutable host intact. Container setup
and encoder discovery do not prove successful real capture or audio.

Other distributions remain best-effort until their exact version/session passes
the same sequence. Keep pairing PINs, credentials, and private network identifiers
out of public reports.

## Publication decision

Review the workflow result for the **exact commit and downloaded files** intended
for publication, including companion-source coverage and checksums. Keep the
package labeled as a preview while the live Ubuntu, receiver, audio, or other
advertised-platform checks remain pending. Publish a stable support claim only
for the platform/session combinations backed by recorded live results.
