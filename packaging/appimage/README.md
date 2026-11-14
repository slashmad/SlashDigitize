# AppImage trial — Fedora45 x86_64

This recipe builds a real type2 AppImage with the official AppImage runtime and
a SquashFS payload. It inventories installed RPM components rather than fetching
unversioned media binaries. Nothing is installed and the old `dist/` is preserved.

Bundled: Python3.15, PyGObject/Cairo, GTK4/libadwaita/GtkSourceView, Unix and media
typelibs, GStreamer plugins/scanner, icons/fonts/schemas, FFmpeg9.0.2 and ffprobe,
arecord/ALSA, common device-metadata utilities and the installed base VapourSynth
package/vspipe. The actual list, file hashes, package versions and supplied
license texts are in the payload's `usr/share/slashdigitize-bundle/manifest.json`
and `usr/share/licenses/`; the external `bundle-manifest.json` repeats inventory.

This first trial uses Fedora45 x86_64 and system glibc2.44 as its tested baseline.
It does not claim compatibility with older distributions. The host supplies its
normal `/bin/sh`, glibc/loader/locale support, display session and kernel/driver
stack. GPU/capture drivers and permissions are not portable bundle contents.
Third-party VapourSynth processing filters and VSRepo metadata are optional and
are not supplied by the installed base VapourSynth package.

## Build

Use Fedora45 x86_64 and system Python3.15. Required build tools are `mksquashfs`,
`rpm`, `ldd`, and the installed application dependencies to collect. The script
refuses a nonmatching FFmpeg9.0.2 pin or a mismatched AppImage runtime hash.

Fetch the official runtime to a temporary file, using the locked asset URL and
hash from [runtime-lock.json](runtime-lock.json):

```sh
curl -fL -H 'Accept: application/octet-stream' \
  https://api.github.com/repos/AppImage/type2-runtime/releases/assets/657374641 \
  -o /tmp/slashdigitize-runtime-x86_64
echo '617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46  /tmp/slashdigitize-runtime-x86_64' | sha256sum -c -
chmod +x /tmp/slashdigitize-runtime-x86_64
python3 -B scripts/build_appimage.py \
  --runtime /tmp/slashdigitize-runtime-x86_64 \
  --work /tmp/slashdigitize-appimage-new-work \
  --out artifacts/appimage
```

The work directory must be new and the output AppImage must not already exist.
Building from a provisioned RPM host is not a bit-reproducible source bootstrap;
the manifest records the exact assembled components. No release signing or
publication is performed.

## Run

```sh
chmod +x SlashDigitize-0.1.0-x86_64-fedora45.AppImage
./SlashDigitize-0.1.0-x86_64-fedora45.AppImage
```

If FUSE mounting is unavailable:

```sh
./SlashDigitize-0.1.0-x86_64-fedora45.AppImage --appimage-extract-and-run
```

Diagnostic arguments: `--ffmpeg -version`, `--ffprobe -version`,
`--arecord --version`, `--gst-inspect gtk4paintablesink`, and `--python -c CODE`.
These choose the bundled programs explicitly. Normal startup only enumerates
devices/capabilities; capture starts on the user's Record action.

## Loader and resources

The launchers invoke the host glibc loader with `--library-path` for each bundled
ELF program. They do not export a global `LD_LIBRARY_PATH` into unrelated host
tools. The bundled interpreter relocates its prefix and its child-interpreter
path, disables user site/CWD imports, and removes startup-only Python environment
variables. GI, GTK input modules, GIO, ALSA and GStreamer paths select payload
components. Fontconfig and image-loader resources are relocated; image-loader
sandboxing stays enabled. Glycin's bubblewrap launcher additionally exposes the
payload read-only inside its sandbox, and its helpers use the bundled library
path even after Glycin clears their environment. Writable caches go into XDG
cache, with a temporary fallback for read-only cache locations. Images with
different mount paths do not share relocation caches.

The vspipe launcher selects the bundled native executable and configures its
embedded Python in a private cache directory. It does not register an interpreter
in the user's existing VapourSynth configuration or depend on host Python.

The process backend is unchanged: native POSIX process groups, direct ALSA PCM,
asynchronous SIGINT stop, WAV finalization and shared Close/Quit guards remain.
The AppImage selects its bundled Adwaita icon theme so a missing host theme
cannot break standard icons. It includes proportional Adwaita/Noto fonts and
Fontconfig generic-family mapping while retaining the desktop's font preference.

## Verify

```sh
python3 -B scripts/test_appimage.py \
  artifacts/appimage/SlashDigitize-0.1.0-x86_64-fedora45.AppImage \
  --report artifacts/appimage/validation.json
```

The test extracts the payload to a fresh temporary directory, uses private
configuration/cache directories and does not import the source checkout. It
checks loaded Python modules/libraries and plugin locations, synthetic FFmpeg
encoding/ffprobe/GStreamer decoding, all58 tests and the eight-page lifecycle
smoke on private Weston with a simulated recorder. No capture devices are opened.
Weston requires permission to create a local Wayland socket; some sandboxes
block this. The test stops its compositor and removes its temporary files.

The first release targets Fedora45 x86_64. Real capture/playback, GPU encoding,
long recordings, physical input and other distributions still require separate
qualification. Releases publish the AppImage with its checksum and inventory;
the build script itself performs no signing or publication.
