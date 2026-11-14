# Validation

Initial development work: 2026-11-14, Codex, Europe/Stockholm.

All **41 tests pass** on Fedora45/Python3.15 and GNOME runtime51/Python3.14,
including the original 34 audio/auto-stop/timelapse tests. New tests cover
cross-owner capture exclusion, bounded timelapse command construction, graceful
nonblocking stop, output draining after a callback failure and host-helper
stop/disconnect behavior with simulated processes, unknown-state blocking,
XRUN tokens split across reads and FFmpeg five-flag pixel-format tables. These do not qualify capture
hardware or recover lost samples.

The private Weston UI test opens all eight workflows, checks dark mode and
shared device exclusion, refuses window/menu/Quit during simulated recording,
requests asynchronous stop, then reads the finalized stereo32-bit WAV header.
Hardware discovery and optional plugin probes are replaced by fixtures.

A second private-display run uses actual host FFmpeg/GPU capability metadata
while capture-device and plugin probes remain stubbed. Encoder and pixel-format
lists populate successfully. The old four-character pixel-format parser was
corrected for FFmpeg's five flags, with a regression test. The original projects
were not modified.

A real CPU FFmpeg encode of a synthetic 2560x1440 frame produced a 1920x1080
yuv420p H.264 output, verified by ffprobe. A synthetic host child was also started
from the installed GNOME51 runtime using the real Flatpak boundary; explicit
stop reached that child, it finalized its shared-path test file, and exited 0.
This is a runtime/transport check using an existing installed app container,
not an installed SlashDigitize Flatpak or real recording qualification.

Wheel, sdist, Fedora45 RPM and SRPM builds succeeded from isolated source copies.
RPM checks include the unit suite, desktop-file validation and strict offline
AppStream validation. The final artifact list/checksums are in `dist/` after a
local build; no packages were installed. The RPM is specific to Python ABI3.15.
The original 1254x1254 icon is stored unchanged in the theme's logical512 slot;
GTK icon lookup and the rendered brand image were verified.

The dark interface with visible workflow navigation and the Audio recording tab
was rendered on a private1440x1000 Weston display and visually inspected.

GNOME51 SDK is not installed locally, so a full GNOME51 Flatpak build has not
been completed. The manifest and isolated build route target51 without automatic
downloads. The AppImage trial was subsequently built; see its validation below.
Real capture, compatible media playback, NVIDIA/other GPU behavior, long-running
performance and Windows/macOS remain unverified.

## GUI migration (2026-11-14, Claude)

The interface was rebuilt on libadwaita boxed lists, pinned action docks and a
grouped sidebar while page logic, recording contracts and JobRegistry were kept.
Validated on a private headless Weston: the unit suite, `tests/test_rows.py`
(GtkComboBoxText/SpinButton/CheckButton semantics on the new rows: no implicit
selection, unknown ids, duplicate labels with distinct ids, rebuild without a
transient selection, single `changed` per change, wheel claimed without a
value change), and `scripts/smoke.py` (all eight workflows, every value control
wheel-guarded, a closed dropdown keeping its value while the page scrolls,
capture exclusion, Close/menu/Quit guards, asynchronous stop and a finalized
WAV), with and without real FFmpeg metadata. All pages were rendered at 1440,
1100 and 820 px and inspected. The wheel guard was exercised through its handler
on real widgets; physical mouse-wheel and touchpad behaviour, keyboard
navigation and screen-reader output still need a manual desktop check.

## Review fixes (2026-11-14, Codex)

The suite now contains **58 tests**:41 pure tests and17 display tests. The
display tests additionally cover the first real popup option, a single option
after rebuilding, an explicit unset placeholder and the99%/100% VU clip
boundary. The lifecycle smoke checks agreement between the recorder flag,
visible clipping badge and completed-recording status, including resetting
the previous take's warning when starting a new one.

Actual verification: all58 tests pass in the rebuilt Fedora45 RPM's `%check`,
with desktop/AppStream validation. Source smoke with real FFmpeg metadata and
the extracted-wheel UI smoke pass with17 widget tests,76 guarded controls,
capture exclusion, protected Close/Quit, asynchronous stop and a finalized
simulated WAV. Wheel/sdist/RPM/SRPM were rebuilt in temporary output directories;
the original `dist/` artifacts were preserved. The GUI retains Claude's design.

The RPM spec now explicitly declares PyGObject, GTK4, libadwaita and
GtkSourceView test/build dependencies. No clean mock buildroot was provisioned
in this run. No real devices, installation or release publication was tested.
The subsequent AppImage trial below implements the dependency bundle discussed
in PORTABILITY.md. A self-contained Flatpak build remains incomplete.

## Initial AppImage trial (2026-11-14, Codex)

The initial trial is retained as `artifacts/appimage-before-release/SlashDigitize-0.1.0-x86_64-fedora45.AppImage`
(220240376 bytes, about210 MiB). SHA256:
`d50c6d1c0c6470d7b31cfcf22c3805d86e433146af7bda21daef87c88428575f`.
The local artifact directory also contains its checksum, component/license
inventory, validation report and an inspected dark GUI preview. The repeatable
assembly and test commands are in [the recipe](../packaging/appimage/README.md).

The official type2 runtime was checksum-verified. The payload includes Python,
GI/Cairo, GTK4.24/libadwaita1.10/GtkSourceView, GStreamer, FFmpeg9.0.2/ffprobe,
arecord1.2.16/ALSA, base VapourSynth79/vspipe, dynamic modules and resources.
Libraries are selected per executable; no global LD_LIBRARY_PATH is exported.
The image uses bundled Adwaita icons and proportional fonts. Glycin retains
its sandbox and can load SVG using the bundled libraries after clearing its
environment. Native startup and recording backends are preserved.

Actual checks on the extracted final payload: all58 tests pass on private
Weston; eight workflows and76 wheel guards pass, including simulated shared
capture ownership, protected Close/Quit, asynchronous SIGINT and a finalized
WAV. Bundled FFmpeg encodes synthetic H.264, ffprobe checks it, and GStreamer
decodes to a fake sink. Base VapourSynth produces a real frame and native
vspipe reads a script. PNG/SVG, font/icon selection, Python/module/plugin paths
and loaded-library boundaries pass. Normal FUSE and extract-and-run starts pass.
A read-only bubblewrap root with only the host shell and its libtinfo plus
glibc/loader also passes the GUI-library/media/image-loader/VS probes, without
host Python, GTK or media libraries. Source GUI smoke and a fresh sdist build
pass; the source archive includes the recipe and excludes memory/prototypes.

This is a Fedora45 x86_64/glibc2.44 local trial. Older distributions, real
capture/playback, GPU acceleration, long recordings and physical input remain
unqualified. Drivers/permissions and optional third-party VapourSynth filters
are external. No installation, signing, publication, commit or push occurred.
All five original `dist/` files, including the pre-migration source, are intact.

## First public release checks (2026-11-14, Codex)

A native GTK probe and the AppImage both created NVIDIA GLES contexts on the
real Wayland desktop. A rendered test window and an independent five-second
SlashDigitize startup used `Gsk.VulkanRenderer`; the real startup reported no
active jobs. The eight-page simulated UI driver also passed on the desktop
renderer. No Mesa EGL or GDK timing warnings were reproduced in these runs.
The reported warnings remain an observation about a prior startup, not evidence
of failed recording or proof that all driver/compositor conditions are covered.
No renderer override, warning filter or driver change was introduced.

The remaining missing-FFmpeg banner condition was corrected: the warning now
shows when FFmpeg is absent even if the encoder list is empty. The UI driver
checks both the missing/empty and available/empty cases. Recording contracts
remain unchanged. README documents the creator's historical tape transfers with
the predecessor applications separately from qualification of the new bundle.

The first public-release candidate is canonical at
`artifacts/appimage/SlashDigitize-0.1.0-x86_64-fedora45.AppImage`
(220240376 bytes). SHA256:
`42c83c735831cbb07cd01b2b8aa4f8899798dbea46c2da0d0f67808eb5737ef9`.
It includes the new README in Help and the missing-FFmpeg warning correction.
All58 extracted-payload tests and eight-workflow smoke checks pass on this
final image. Normal FUSE/NVIDIA Vulkan desktop startup and extract-and-run pass.
The current native wheel/sdist/RPM/SRPM also build; all58 tests and desktop/
AppStream validation pass in the RPM check. Initial RPM attempts hit sandbox
write/socket restrictions; the final build used dedicated temporary files and
authorized outside-sandbox execution. No packages were installed.
