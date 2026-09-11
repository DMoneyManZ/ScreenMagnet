# ScreenMagnet — third-party notices and source

ScreenMagnet is distributed under GPL version 3 or later. The application license
is included with the release, and its buildable source, packaging scripts,
patches, and tests are in `source/ScreenMagnet-source.tar.gz`.

The release data directory is beside the application resources in each package;
look for this file and the adjacent `source` and `licenses` directories. Original
upstream notices remain authoritative for their respective components.

| Component | Included material |
|---|---|
| Python 3.13 | Exact interpreter version in `licenses/components.json`; Python license and incorporated-library notices in `licenses/python` |
| PySide6 Essentials and Shiboken 6.11.1 | Original license texts in `licenses/pyside-setup`; corresponding binding sources in the matching `pyside-setup` archive |
| Qt Base, SVG, image-format plugins, and Wayland 6.11.1 | Version-matched source archives in `source/dependencies`, with extracted license and attribution files under `licenses` |
| zeroconf 0.150.0 | LGPL 2.1 or later; complete PyPI source distribution and original notices |
| ifaddr | Exact installed version in the manifest, with its PyPI source distribution and original notices |
| Patched DoubleTake and its Go dependencies | Patched application source, Go module manifests, and vendored dependency sources in `source/DoubleTake-patched-source.tar.gz`; original notices under `licenses/doubletake` |
| Go runtime | Build toolchain version in the manifest and its license in `licenses/go` |
| PyInstaller 6.22.2 bootloader | Original terms, including its distribution exception, in `licenses/pyinstaller/COPYING.txt` |

Qt and PySide provide LGPL version 3 licensing options; their source archives
also contain notices for incorporated third-party code. Python, Go, ifaddr,
and the individual vendored Go modules retain their upstream licenses. These
components are not relicensed by this summary. Preserve their original notices.

`licenses/components.json` records the application/runtime versions, dependency
source download locations, archive SHA-256 hashes, and the vendored Go module
inventory. The Qt source downloads come from The Qt Company. The zeroconf and
ifaddr archives are selected for the exact installed versions from PyPI and
verified against PyPI's published SHA-256 digests.

Linux packages additionally include `licenses/system-libraries.json`, which
maps the collected system libraries to their exact Ubuntu binary and source
package versions. Original distribution copyright files and referenced common
license texts are in `licenses/system`; matching source package downloads are
in `source/system`. The bundled ICU libraries from the Qt wheel have their
version-matched source and notices recorded in that same manifest. These system
components retain their individual upstream licenses.

## Rebuilding or modifying libraries

Extract `source/ScreenMagnet-source.tar.gz` and follow its platform build scripts
and documentation. Extract the patched DoubleTake source archive, including its
`vendor` directory, to build that binary with the supplied Go dependencies.
Rebuilding the application packaging also requires the listed build tools and
network access for upstream dependency downloads.

The Qt/PySide runtime libraries remain separate dynamic libraries in the packaged
runtime directory. An interface-compatible modified library can replace the
corresponding file after quitting ScreenMagnet. You may modify the libraries and
reverse engineer the combined application to debug those modifications as
permitted by their applicable licenses. A signing key is not required to run a
rebuilt application. For a modified dependency build, adjust the pinned versions,
component manifest, and corresponding sources to match the libraries distributed.

The Python zeroconf and ifaddr source distributions are included for modification
and rebuilding as well. Application Python modules may be frozen into the
PyInstaller archive; rebuild the package with modified modules using the included
application source and build scripts.

## Separately installed Windows prerequisites

The Windows GStreamer and Microsoft Visual C++ Redistributable installers are
downloaded directly from their upstream providers at installation time. They are
not distributed in the ScreenMagnet package or its source archives. Their own
installer terms and notices apply separately. ScreenMagnet does not claim
ownership of, or change the license of, those prerequisites.
