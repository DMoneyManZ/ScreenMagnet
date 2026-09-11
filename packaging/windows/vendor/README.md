# Historical Windows binaries — excluded from releases

The files in this directory are retained as historical development artifacts.
**Current release packages do not include or use either `doubletake.exe` or
`VirtualDisplayDriver-installer.zip` from here.** Their presence in the repository
does not make them approved release inputs.

## Historical `doubletake.exe`

The checked-in sender predates the reproducible preview build. Its exact Windows
capture source was not preserved in the project patch, so its corresponding
source is unavailable and CI cannot reproduce that binary.

Earlier development notes report that this binary cast video to an AirPlay TV,
without Windows audio. That historical result applies only to this binary; it
does not establish real-receiver behavior for a newly built sender.

Current previews compile the pinned upstream sender with
[`patches/0001-screenmagnet-fixes.patch`](../../../patches/0001-screenmagnet-fixes.patch),
including the reconstructed Windows capture and loopback-audio code. The
[Windows build script](../build.ps1) rejects this historical vendor directory as
a sender input. Do not ship the old binary alongside the source-built preview
as a fallback or an alternate “known-good” executable.

The reconstruction is not recovered original source. Real screen capture,
monitor-index mapping, receiver behavior, and synchronized Windows audio still
need live-hardware verification. A successful build or synthetic runtime test
is not evidence that those paths work with a particular TV.

## Historical `VirtualDisplayDriver-installer.zip`

Recorded provenance of the retained archive:

- Original download: [VDD Control 25.7.23](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VDD.Control.25.7.23.zip).
- Recorded size: 71,225,903 bytes.
- Recorded SHA-256: `a701f2272e9fcf382849b24f913c6dd07597b3b1116525f2e90182f019609154`.

This archive is excluded from current ScreenMagnet packages. ScreenMagnet setup
neither bundles nor automatically installs the virtual-display driver. When the
driver is absent, the app links the
[official upstream releases](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases)
for a separate installation following that release's instructions. Administrator
approval is required for driver installation. Mirror casting does not require
this optional driver.

See [extended-display status](../../../docs/EXTENDED-DISPLAY.md) for the
implementation and pending live-driver/receiver checks. The historical archive
is provenance material, not the recommended installation source.
