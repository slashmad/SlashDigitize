# Distribution and portability

Fedora 45 native RPM is the first packaging target. Native GTK/GI/GStreamer and
ALSA dependencies are declared in the spec. FFmpeg and ffprobe are required by
executable path so either suitable distro or third-party packages may provide
them. Codec and hardware support must be checked from the actual builds.

The Flatpak manifest targets GNOME Platform/SDK 51; source is copied explicitly
without Git history, captures or local agent memory. Host processes require
host Python, arecord, FFmpeg and the optional VapourSynth stack. Output paths,
host `/tmp` separation, signal delivery and driver access require dedicated
testing, beyond a successful package build.

A Fedora45 x86_64 AppImage trial is now built with bundled Python/GI/Cairo,
GTK4/libadwaita/GtkSourceView, GStreamer, FFmpeg9.0.2/ffprobe, arecord/ALSA and
base VapourSynth/vspipe. It uses a verified official type2 runtime and an
inventoried SquashFS payload; the GUI is not a wrapper around host Python/GTK.
Per-program loader paths avoid exporting a global LD_LIBRARY_PATH. Required
dynamic modules, fonts/icons, schemas and component license texts are included.
The tested build baseline is Fedora45 with glibc2.44. Compatibility with older
distributions and the host GPU/capture driver stack needs separate validation.
See [the AppImage recipe](../packaging/appimage/README.md) for commands and limits.

Windows/macOS need alternative capture backends, device discovery, lifecycle
handling and installers. arecord/ALSA and V4L2 remain Linux-specific. Shared
navigation and command-building code do not establish capture parity on those
systems. Neither the Linux package nor an AppImage supplies that parity.

## Bundled dependency distribution

A distribution containing the application's user-space dependencies is feasible.
It is a separate packaging target from the native RPM, whose dependencies are
resolved by the package manager. The existing Flatpak recipe is not yet such a
complete bundle: it intentionally launches host media tools through the host
bridge. Merely adding FFmpeg inside `/app` would not make these host processes
use it.

As checked on 2026-11-14, the upstream download page lists **FFmpeg9.0.2** as the
latest stable release; this host already reports9.0.2. See the
[official downloads and verification instructions](https://ffmpeg.org/download.html).
This establishes a version, not a guaranteed set of codecs or GPU support.
Bundle a pinned, verified build with matching ffprobe; update the pin through
tested releases rather than fetching an unversioned “latest” binary at startup.

The single-file AppImage trial supplies Python/PyGObject/Cairo,
GTK4/libadwaita/GtkSourceView and typelibs, schemas,
icons, GStreamer with the chosen preview plugins, FFmpeg/ffprobe and their codec
libraries, plus arecord/libasound with required ALSA configuration. Base
VapourSynth/vspipe is included; VSRepo and third-party processing plugins remain
separate. The bundle records component licenses, versions and file hashes.
Synthetic codec/filter checks exercise the actual extracted payload.

Kernel support, device permissions and the host-compatible GPU/Blackmagic driver
stack remain external. AppImage's
[dependency and platform-baseline guidance](https://docs.appimage.org/introduction/concepts.html)
also requires a defined Linux/glibc baseline: copying binaries from Fedora45
does not establish compatibility with older distributions.

Flatpak is the alternative: use GNOME51 for the GUI stack and bundle the media
components absent from, or requiring a different version than, that runtime.
[Flatpak documents both mechanisms](https://docs.flatpak.org/en/latest/dependencies.html).
It needs an explicit sandbox-versus-host execution policy for FFmpeg/ffprobe,
arecord and vspipe, and renewed path/device/stop/finalization tests. The current
host-only transport must not be silently redirected. The GNOME51 SDK is not
installed on the development host, so this Flatpak route remains unbuilt. The
subsequent AppImage trial supplies the user-space stack independently of Flatpak;
it does not establish capture qualification or older-distribution compatibility.
