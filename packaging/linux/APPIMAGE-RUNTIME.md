# AppImage executable runtime provenance

ScreenMagnet embeds the x86_64 Type 2 runtime built from
AppImage/type2-runtime commit `75849dce7cc37e4319b633df1f116ca895c71a12`.
Its SHA-256 is
`1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf`.
The staging helper verifies this digest even when using an existing cache;
an updated upstream `continuous` download fails closed until its source and
dependency correspondence have been reviewed and all pins updated together.

The [upstream x86_64 build log](https://github.com/AppImage/type2-runtime/actions/runs/28063784345/job/83083595830)
records the June 23, 2026 Docker build using Alpine 3.21 image digest
`sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d`.
Its link command uses squashfuse, squashfuse_ll, zstd, zlib, fuse3, mimalloc,
and static musl. Squashfuse reports only ZLIB and ZSTD compression support.
The original runtime license also identifies public-domain MD5 code in
`src/runtime/runtime.c`; retain that source header when rebuilding.

The accompanying `source/appimage-runtime/` payload contains:

- The exact runtime source archive, including its Makefile, Docker and chroot
  build scripts, workflow and `patches/libfuse/mount.c.diff`.
- libfuse 3.15.0 and squashfuse 0.5.2 source archives, using the checksums
  pinned in that runtime revision's dependency script. Apply the supplied
  libfuse patch before building, as that script does.
- musl 1.2.5, zstd 1.5.6, zlib 1.3.2, mimalloc 2.1.7 and fortify-headers
  1.1 source archives (the latter preserves inline header code).
- `alpine-runtime-recipes.tar.gz`: the original Alpine recipes and patches
  for musl **1.2.5-r11**, zstd **1.5.6-r2**, zlib **1.3.2-r0**,
  mimalloc2 **2.1.7-r0**, fortify-headers **1.1-r5**, and GCC **14.2.0-r4**, matching versions in the
  binary's build log. These come from aports commit
  `9ba44d139997adf2fc29046f578ab596d05b7fc5`. In particular, use the musl
  patches and mimalloc secure-mode configuration; upstream version numbers
  alone do not describe the linked Alpine libraries.

`licenses/appimage-runtime/` contains the original notices and license
texts, including libfuse's LGPL 2.1 and GPL 2 texts, musl COPYRIGHT,
squashfuse LICENSE, zstd LICENSE/COPYING, zlib LICENSE, mimalloc LICENSE and
fortify-headers LICENSE.
GCC's original GPLv3 and GCC Runtime Library Exception 3.1 are included as
`GCC-COPYING3` and `GCC-COPYING.RUNTIME` for compiler-generated runtime code.
The GCC compiler itself is not shipped. Its source remains available from
[GCC 14.2.0](https://gcc.gnu.org/pub/gcc/releases/gcc-14.2.0/); the matching
Alpine patches are in the recipe archive.

To rebuild or modify the runtime, extract its source, use the included
library sources and matching Alpine recipes/patches, and follow its
`BUILD.md` and `scripts/docker/` instructions. The upstream workflow writes
`https://github.com/AppImage/type2-runtime/commit/75849dc` to
`src/runtime/version` before invoking `scripts/build-runtime.sh`. Preserve
that build's package versions rather than resolving a current Alpine mirror
when reproducing the original input set. The provided source permits
rebuilding with a modified libfuse; ScreenMagnet does not require a signed
runtime. Pass the replacement executable to appimagetool's `--runtime-file`.
Rebuilding is not claimed to be bit-for-bit reproducible.

`appimage-runtime-manifest.json` records every input URL and checksum, the
upstream build reference and the staged source checksums. This runtime
payload is separate from the application's Python, Qt and sender sources.
