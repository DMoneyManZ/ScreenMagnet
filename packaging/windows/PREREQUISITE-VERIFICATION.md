# Windows prerequisite verification

The online setup downloads prerequisites directly from their publishers. It
does not bundle the GStreamer or Microsoft redistributable installers.

## GStreamer 1.28.5, MSVC x86-64

The official installer is not Authenticode signed. GStreamer publishes a
[SHA-256 checksum](https://gstreamer.freedesktop.org/data/pkg/windows/1.28.5/msvc/gstreamer-1.0-msvc-x86_64-1.28.5.exe.sha256sum)
and a [detached OpenPGP signature](https://gstreamer.freedesktop.org/data/pkg/windows/1.28.5/msvc/gstreamer-1.0-msvc-x86_64-1.28.5.exe.asc)
beside the [installer](https://gstreamer.freedesktop.org/data/pkg/windows/1.28.5/msvc/gstreamer-1.0-msvc-x86_64-1.28.5.exe).
The checksum retrieved from that official HTTPS URL on 2026-09-11 is:

```text
51ee5eaec33008e8409d8cf6f6884457f22aa3bd515f8856f993a3eaab903530  gstreamer-1.0-msvc-x86_64-1.28.5.exe
```

`install-prerequisites.ps1` pins this reviewed value, filename, version, and
official URL. CI downloads the published checksum and requires it to match the
pin, then hashes the downloaded installer before execution. End-user setup
requires the bundled manifest to match the same release pin and hashes its own
download before execution. A changed upstream file or checksum fails closed;
upgrading GStreamer requires reviewing and updating the source pin.

This is checksum pinning anchored in the reviewed official HTTPS publication.
It is not Authenticode or OpenPGP verification: setup does not claim to verify
the detached signature and does not require GnuPG on the user's computer.

## Microsoft Visual C++ runtime

CI follows Microsoft's HTTPS `aka.ms` link only to allowed Microsoft download
hosts, requires a valid Windows Authenticode signature, then records the
resolved URL, SHA-256, and product version in the release manifest. End-user
setup requires both the manifest checksum and valid Authenticode before
executing a newly downloaded installer. Invalid signatures and hash mismatches
stop installation.

Existing prerequisites are checked for their required version and, for
GStreamer, the capture/encoding plugins. Those runtime checks do not assert how
an already installed prerequisite was originally downloaded.

Regression tests execute the PowerShell verification functions with controlled
signature/hash results, plus a real tampered-file hash check. Native CI also
downloads and verifies the actual upstream installers before runtime smoke
tests. No test captures the desktop or sends input to a real television.
