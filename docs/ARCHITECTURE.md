# Architecture

`slashdigitize.app` owns the Adw application and delegates user Quit to the
window's Close guard. `video.gui.MainWindow` composes the imported video UI and
the new shared shell. `shell.WorkflowTab` lazily creates expensive/optional
workflow pages and retains their state; there is no dependency on sibling
source checkouts.

The presentation layer lives in `slashdigitize.ui`. `ui.widgets` provides the
page scaffold (`page_view`: scrolling, width clamp, pinned action dock and a
per-page breakpoint that stacks `columns`), boxed-list builders, GtkSourceView
command/script/log views, the Cairo `StereoMeter`/`LevelHistory` and the
capture-phase wheel guard. `ui.rows` adapts libadwaita rows to the small legacy
API the imported pages use: `ChoiceRow` is an `Adw.ComboRow` with the id-based
GtkComboBoxText methods and `changed` signal, `SpinRow`/`SwitchRow` wrap
`Gtk.SpinButton`/`Gtk.Switch` in action rows (the Adw equivalents are final
types), and `EntryRow`/`PathRow` add placeholder hints and browse buttons.
`tests/test_rows.py` pins these semantics. Page layouts are Python modules
(`video/*_layout.py`) that register widgets under the former GtkBuilder ids in
a `ui.widgets.Layout`, so page logic binds to them unchanged. `style.css`
overrides libadwaita CSS variables; bundled symbolic icons under
`assets/icons` keep the navigation independent of the desktop icon theme.

ChoiceRow keeps an explicit disabled “Choose…” placeholder in its native Adw
model. The legacy model and active indices exclude it; native `selected`
indices include it (real entries start at1). This preserves append-without-
selection and makes the first real option selectable after a clear. A visible
real value always has a corresponding logical active index. Level meters use
the same full-scale observation boundary as arecord's VU reporting (100% /0 dBFS);
near-full-scale values are not labelled clipping. These are VU observations,
not true-peak measurements.

`video.gui.MainWindow` derives session state from the page owners
(`activities()`): REC is shown only for an actual audio or video capture, never
for probes, live view, finalization or exports. The close guard is the
JobRegistry check presented as a dialog.

`audio.app.RecorderPage` is embedded in the Audio recording tab. `audio.core`
and `audio.auto_stop` preserve the pure profile, parsing, finalization and
read-only analysis logic. The page retains capture/stop state until stderr has
been drained, the OS process has exited and the GUI completion handler has run.

`jobs.JobRegistry` queries the actual owners for Close/Quit and conservative
cross-workflow capture exclusion. Unknown job state fails closed. Export jobs
are independent of capture exclusivity. Job registration is not permission to
interrupt a backend or delete temporary input files before completion.

`process.BackendProcess` owns process transport. Native processes use dedicated
POSIX process groups. In Flatpak it sends a standalone `host_bridge` program to
host Python using `flatpak-spawn --host`; the bridge owns the host process group
and accepts a small stop message over stdin. Audio samples remain in arecord's
WAV, never in the control channel. The bridge forwards diagnostics/output as
needed, gracefully stops on control-channel disconnect and waits for the child.
No automatic TERM/KILL escalation is configured.

The `video` modules preserve FFmpeg capture/edit/timelapse and VapourSynth
features. Their UI/process responsibilities are inherited and can be extracted
incrementally; they are not a complete new backend architecture. Feature probes
inside some lazily opened pages still run synchronously and may need further
profiling. The global FFmpeg rescan already runs outside the UI thread.

The original recording contracts remain: explicit direct hardware PCM,
BlackmagicIO default, S32_LE/48000/stereo, no overwrite or backend fallback,
graceful finalization, protected Close and honest XRUN reporting. Auto-stop is
disabled by default, read-only, failure-isolated and uses the existing stop path.
