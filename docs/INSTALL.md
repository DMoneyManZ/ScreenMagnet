# Install ScreenMagnet

[Project overview](../README.md) · [Linux verification status](LINUX-RELEASE-READINESS.md) · [Extended displays](EXTENDED-DISPLAY.md)

ScreenMagnet is a tray application for sending a screen to an AirPlay receiver.
The downloadable packages include the application runtime and patched
`doubletake` sender. Capture dependencies and verification differ by platform.

## Ubuntu and Linux AppImage

**Ubuntu 22.04 and Ubuntu 24.04, x86_64, are the Linux release baseline.**
SteamOS/Steam Deck and Bazzite use the container setup below. Other glibc-based
x86_64 distributions are best-effort; the AppImage is not an ARM or Alpine/musl
build.

The AppImage includes Python, PySide6, zeroconf, and the sender. You do not need
to install Python or copy Python packages into the system interpreter. Your
desktop still needs its graphics libraries and a screen/audio capture route:
GStreamer tools and plugins, with a usable H.264 encoder, natively or in the
prepared distrobox.

### Download the Linux files

Download these files from the same ScreenMagnet release or preview build into
one folder:

- `ScreenMagnet-x86_64.AppImage`
- `ScreenMagnet-x86_64.AppImage.sha256`
- `install-appimage.sh`
- `screenmagnet.svg`
- `screenmagnet-linux.sh`

Use the supplied icon; it is the application's existing ScreenMagnet artwork.
The installer can also read a release-wide `SHA256SUMS` file when the individual
`.sha256` file is absent. The manifest must contain exactly one checksum record
naming the selected AppImage.

From a terminal in the download folder, verify the AppImage:

```bash
sha256sum --check ScreenMagnet-x86_64.AppImage.sha256
```

Continue only if verification reports `OK` for that file. The installer repeats
the verification on the copy it will install and refuses to replace an existing
installation if the checksum fails.

### Prepare Ubuntu capture dependencies

Run the dependency setup as your normal user:

```bash
bash ./screenmagnet-linux.sh install-deps
bash ./screenmagnet-linux.sh doctor
```

`install-deps` downloads packages with your system package manager and requests
administrator authorization through `sudo`. On Ubuntu it installs GStreamer
tools and the base/good/bad/ugly plugin sets, X11 utilities, and the desktop
libraries used by Qt. It requires internet access. `doctor` reports what is
available without installing packages or preparing a container.

A registered encoder alone does not prove that your GPU can encode a real
capture. The release's live receiver/audio checks remain separate from the
package and dependency checks.

### Install the application and menu entry

```bash
bash ./install-appimage.sh
```

The default input is the AppImage beside that script. To select a file elsewhere:

```bash
bash ./install-appimage.sh "/path with spaces/ScreenMagnet-x86_64.AppImage"
```

Keep the checksum and `screenmagnet.svg` beside the selected AppImage. From a
source checkout, the helper also recognizes the existing `app/assets/screenmagnet.svg`.

**Do not run the AppImage installer with sudo.** It installs into your user
account, adds the application-menu entry and icon, and does not launch the app
or start a cast. When ready, open **ScreenMagnet** from your application menu.

Default installed paths, when `XDG_DATA_HOME` is unset:

| Path | Purpose |
|---|---|
| `~/.local/share/screenmagnet/ScreenMagnet-x86_64.AppImage` | Verified application |
| `~/.local/share/screenmagnet/screenmagnet` | Launch wrapper |
| `~/.local/share/applications/screenmagnet.desktop` | Application-menu entry |
| `~/.local/share/icons/hicolor/scalable/apps/screenmagnet.svg` | Existing ScreenMagnet icon |

A custom absolute `XDG_DATA_HOME` changes those locations. Paths containing
spaces are supported. The helper never installs system packages; that belongs
to `screenmagnet-linux.sh install-deps`.

The installed wrapper consistently uses AppImage **extract-and-run** mode, so it
does not depend on FUSE 2 or a usable `/dev/fuse`. This can add startup time and
needs temporary disk space. Keep the installed AppImage and wrapper together.
You can also launch the installed copy explicitly:

```bash
"${XDG_DATA_HOME:-$HOME/.local/share}/screenmagnet/screenmagnet"
```

## SteamOS, Steam Deck, and Bazzite

Use Desktop Mode where applicable. Keep the host's read-only/immutable system
intact; do not unlock it or use Ubuntu package commands on the host.

With distrobox and its supported container engine available, run:

```bash
bash ./screenmagnet-linux.sh setup-steamos
bash ./screenmagnet-linux.sh doctor
bash ./install-appimage.sh
```

The `setup-steamos` command is also the container setup path for Bazzite. It
creates or reuses the `screenmagnet` distrobox, installs GStreamer and X11 tools
inside it, and verifies encoder availability before recording the setup as
ready. The first setup needs internet access and may take several minutes.
It does not unlock the host filesystem. If distrobox or a container engine is
missing, install it through your distribution's supported process first.

The AppImage exposes its bundled sender under your user data directory when it
runs so the container can access it. Container setup does not prove receiver
compatibility, successful pairing, or working audio. SteamOS/Bazzite hardware
validation remains part of the preview's manual checks.

## First connection

Open the tray menu, select a discovered receiver and a monitor, and follow any
pairing prompt. The receiver must be reachable on your network. The desktop may
also present a screen-sharing permission dialog, depending on its capture route.
Start a cast only when you are ready to share the chosen screen.

If the app opens but no receiver appears, inspect the network/receiver setup.
If a receiver appears but capture fails, run `doctor` and check the desktop's
GStreamer, encoder, and capture permissions. Packaging tests and synthetic smoke
tests do not guarantee a successful real receiver connection or audio stream.

## Update or remove the Linux AppImage

Quit ScreenMagnet before updating. Download the new AppImage and matching
checksum, then run the helper again. It verifies the new copy before replacing
the installed application. Existing configuration and pairing data are retained.

To remove the installed AppImage and its desktop integration:

```bash
bash ./install-appimage.sh --uninstall
```

From a source checkout, the same operation is:

```bash
bash ./packaging/linux/install-appimage.sh --uninstall
```

The helper removes only the AppImage, its wrapper, and the menu/icon entries it
installed. It does not delete settings, pairing data, source environments,
container configuration, or unrelated files in the ScreenMagnet data directory.
If source setup subsequently replaced the menu entry, the AppImage uninstaller
leaves that replacement entry and icon in place. No logout is normally required;
a desktop that caches menus may need a menu refresh before the entry disappears.

## Windows setup

Download `ScreenMagnet-Setup.exe` from the intended release or preview build and
run it. The installer includes the application and patched sender, and runs the
GStreamer and Visual C++ runtime prerequisites as needed. It uses the standard
Windows administrator prompt for those system-wide prerequisites.

**Internet access is required during setup.** The GStreamer prerequisite is the
official upstream online installer; including that installer in ScreenMagnet's
setup does not make all GStreamer payloads available offline. Wait for setup to
finish before opening ScreenMagnet from the Start menu.

A successful setup or Windows smoke test is not a guarantee of discovery,
pairing, video, or audio with a particular real receiver. Use the preview's
reported validation results to distinguish package checks from live casting.
See [extended-display guidance](EXTENDED-DISPLAY.md) for the separate optional
Windows virtual-display setup.

## Source setup and diagnostics

For development or recovery, use the repository-root launcher:

```bash
bash ./screenmagnet-linux.sh setup-source
bash ./screenmagnet-linux.sh run-source
```

Source mode uses an isolated Python 3.13/3.14 environment. It is separate from the
AppImage installation and requires build/download dependencies. Do not replace
Ubuntu's system Python or mix another Python version's `site-packages` into it.

Useful checks from a checkout:

```bash
bash ./screenmagnet-linux.sh doctor
python3 -m unittest discover -s app/tests -p test_appimage_install.py -v
```

The installer tests use synthetic executable files and temporary user folders;
they do not run the real application or cast a screen. The full
[Linux release guide](LINUX-RELEASE-READINESS.md) describes package verification
and the outstanding live desktop/receiver tests.

## Support development

[Support ScreenMagnet with PayPal](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=demurphy242%40gmail.com&item_name=Support+ScreenMagnet+development&currency_code=USD). Contributions are optional; choose any amount.
