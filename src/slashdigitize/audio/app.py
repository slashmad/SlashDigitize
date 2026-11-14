from __future__ import annotations

import os
import math
import re
from pathlib import Path
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .auto_stop import AnalysisUpdate, AutoStopConfig, GrowingWavAnalyzer
from slashdigitize.process import BackendProcess, host_command
from slashdigitize.ui import widgets as w
from slashdigitize.ui.rows import EntryRow, PathRow, SpinRow, SwitchRow
from slashdigitize.video.i18n import _

from .core import (
    CaptureDevice,
    CaptureProfile,
    XrunCounter,
    capture_devices_with_default,
    capture_error_detail,
    capture_exit_was_clean,
    drain_stderr_and_wait,
    ensure_directory,
    free_bytes,
    parse_vu,
    parse_capture_devices,
    percent_to_dbfs,
    recording_path,
    safe_stem,
)


MIN_FREE_BYTES = 10 * 1024**3
AUTO_STOP_COUNTDOWN_SECONDS = 15

def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.2f} {unit}"
        number /= 1024
    raise AssertionError("unreachable")


class RecorderPage(Gtk.Box):
    def __init__(self, window, jobs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.window = window
        self.jobs = jobs
        self._probing = False
        self._disposed = False
        self.profile = CaptureProfile()
        self.capture_devices: list[CaptureDevice] = list(
            capture_devices_with_default(())
        )
        self.process: BackendProcess | None = None
        self.destination: Path | None = None
        self.completed_destination: Path | None = None
        self.media: Gtk.MediaFile | None = None
        self.auto_stop_analyzer: GrowingWavAnalyzer | None = None
        self.auto_stop_deadline: float | None = None
        self.stop_requested = False
        self.auto_stop_requested = False
        self.started_at = 0.0
        self.xruns = 0
        self._xrun_counter = XrunCounter()
        self.clipped = False
        self.meter_tail = ""

        self._outcome: str | None = None
        self.last_vu: tuple[int, int] | None = None
        self._last_db = [w.FLOOR_DB, w.FLOOR_DB]
        self._free_checked = 0.0

        # ---------- hero: state, timer, stats, meters -----------------------
        self.state_pill = w.pill(_("READY"), "accent")
        self.device_chip = w.chip(self.profile.device)
        chips = Gtk.Box(spacing=6, halign=Gtk.Align.END, hexpand=True)
        for widget in (self.device_chip, w.chip("48 kHz"), w.chip("S32_LE"), w.chip(_("Stereo"))):
            chips.append(widget)
        top = Gtk.Box(spacing=8)
        top.append(self.state_pill)
        top.append(chips)

        self.timer = w.label("00:00:00", css=("sd-timer",))
        self.file_label = w.label(_("No file yet"), css=("sd-meta",), ellipsize=True, selectable=True)
        timer_box = w.vbox(self.timer, self.file_label, spacing=0)
        timer_box.set_hexpand(True)
        stats = Gtk.Grid(column_spacing=28, row_spacing=2, valign=Gtk.Align.CENTER)
        self.size_value = self._stat(stats, 0, _("Size"), "0 B")
        self.free_value = self._stat(stats, 1, _("Free"), "—")
        self.xrun_pill = w.pill("0", "ok")
        self.clip_pill = w.pill(_("None"), "ok")
        self._stat_widget(stats, 2, "XRUN", self.xrun_pill)
        self._stat_widget(stats, 3, _("Clipping"), self.clip_pill)
        mid = Gtk.Box(spacing=18)
        mid.append(timer_box)
        mid.append(stats)
        self.status = w.label(_("Ready"), css=("sd-status-line",), wrap=True, selectable=True)

        self.meter = w.StereoMeter()
        self.history = w.LevelHistory(seconds=60, rate=4)
        history_head = Gtk.Box()
        history_head.append(w.caption(_("Level history · 60 s")))
        hint = w.label(_("Meters follow arecord's VU output while recording (not true peak)."),
                       css=("sd-meta",), xalign=1)
        hint.set_hexpand(True)
        history_head.append(hint)
        self.hero = w.vbox(top, mid, self.status, self.meter, history_head, self.history, spacing=14)
        self.hero.add_css_class("sd-hero")

        # ---------- source ---------------------------------------------------
        self.refresh_devices_button = w.icon_button("view-refresh-symbolic", _("Rescan ALSA hardware devices"))
        source = w.group(_("Source"), suffix=self.refresh_devices_button)
        self.device_model = Gtk.StringList.new([device.display_label for device in self.capture_devices])
        self.device_dropdown = Adw.ComboRow(title=_("Capture device"), model=self.device_model,
                                            subtitle=_("Direct hw: device · no PipeWire or plugin fallback"))
        self.device_dropdown.set_use_markup(False)
        w.guard_scroll(self.device_dropdown)
        source.add(self.device_dropdown)
        fmt = w.action_row(_("Format"), "S32_LE · 48 000 Hz · 2 " + _("channels"))
        fmt.add_suffix(w.pill(_("Fixed")))
        source.add(fmt)

        # ---------- destination ----------------------------------------------
        self.dest = w.group(_("Destination"))
        self.name_entry = EntryRow(_("Take name"), "Cassette001_SideA")
        self.folder_entry = PathRow(_("Folder"), str(Path.home() / "Music"), icon="folder-open-symbolic",
                                    tooltip=_("Choose recording folder"))
        self.browse_button = self.folder_entry.button
        self.target_row = w.action_row(_("Saved as"), "")
        self.target_row.set_subtitle_selectable(True)
        self.target_row.add_suffix(w.pill(_("Never overwrites"), "ok"))
        for row in (self.name_entry, self.folder_entry, self.target_row):
            self.dest.add(row)
        self.name_entry.connect("changed", lambda *_: self._update_target())
        self.folder_entry.connect("changed", lambda *_: self._update_target())

        # ---------- auto-stop -------------------------------------------------
        auto = w.group(_("Automatic tape-end stop"), _("Reads the growing WAV only — never touches the capture"),
                       w.pill(_("Experimental"), "warn"))
        self.auto_stop_check = SwitchRow(_("Enable for the next recording"),
                                         _("Off by default; a 15 s countdown runs first and returning sound cancels it"))
        self.auto_stop_earliest = SpinRow(_("Not before"), 0, 180, 1, 30, subtitle=_("minutes into the take"))
        self.auto_stop_silence = SpinRow(_("Low activity for"), 5, 600, 5, 60, subtitle=_("seconds, both channels"))
        self.auto_stop_threshold = SpinRow(_("Threshold"), -90, -20, 1, -60, subtitle="dBFS")
        self.auto_stop_status = w.label(_("Auto-stop is off."), css=("dimmed",), wrap=True)
        self.disable_auto_stop_button = w.label_button(_("Disable"), None, css=("pill", "flat"))
        self.disable_auto_stop_button.set_sensitive(False)
        status_row = Gtk.ListBoxRow(activatable=False)
        status_box = Gtk.Box(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(status_box, f"set_margin_{side}")(12)
        self.auto_stop_status.set_hexpand(True)
        status_box.append(Gtk.Image.new_from_icon_name("alarm-symbolic"))
        status_box.append(self.auto_stop_status)
        status_box.append(self.disable_auto_stop_button)
        status_row.set_child(status_box)
        for row in (self.auto_stop_check, self.auto_stop_earliest, self.auto_stop_silence,
                    self.auto_stop_threshold, status_row):
            auto.add(row)

        content = w.vbox(self.hero, w.columns(source, self.dest), auto, spacing=22)

        # ---------- dock -------------------------------------------------------
        self.dock_status = w.dock_status()
        self.probe_button = w.label_button(_("Check device"), "emblem-ok-symbolic", css=("pill", "flat"),
                                           tooltip=_("Open the selected device briefly to verify the format"))
        self.play_button = w.label_button(_("Play"), "media-playback-start-symbolic", css=("pill", "flat"),
                                          tooltip=_("Play the completed recording"))
        self.play_button.set_sensitive(False)
        self.record_button = w.label_button(_("Record"), "media-record-symbolic", css=("sd-record",),
                                            tooltip=_("Start recording (Ctrl+R)"))
        self.stop_button = w.label_button(_("Stop"), "media-playback-stop-symbolic", css=("sd-record", "stop"),
                                          tooltip=_("Stop and finalize the WAV (Ctrl+R)"))
        self.stop_button.set_sensitive(False)
        self.stop_button.set_visible(False)
        self.append(w.page_view(content, w.dock(self.dock_status, self.probe_button, self.play_button,
                                                self.record_button, self.stop_button)))

        self.browse_button.connect("clicked", self._browse)
        self.device_dropdown.connect("notify::selected", self._device_selected)
        self.refresh_devices_button.connect("clicked", self._refresh_devices)
        self.probe_button.connect("clicked", self._probe)
        self.record_button.connect("clicked", self._start)
        self.stop_button.connect("clicked", self._stop)
        self.play_button.connect("clicked", self._play)
        self.auto_stop_check.connect("toggled", self._auto_stop_toggled)
        self.disable_auto_stop_button.connect("clicked", self._disable_auto_stop)
        self._auto_stop_toggled(self.auto_stop_check)
        self._update_target()
        self._refresh_devices(None)
        self._tick_id = GLib.timeout_add(250, self._tick)
        self._tick()

    # ---------- presentation helpers -------------------------------------------
    def _stat(self, grid, col, title, value):
        lbl = w.label(value, css=("title-4", "numeric"))
        self._stat_widget(grid, col, title, lbl)
        return lbl

    def _stat_widget(self, grid, col, title, widget):
        grid.attach(w.caption(title), col, 0, 1, 1)
        widget.set_halign(Gtk.Align.START)
        grid.attach(widget, col, 1, 1, 1)

    def _update_target(self) -> None:
        folder = Path(self.folder_entry.get_text()).expanduser()
        stem = safe_stem(self.name_entry.get_text())
        self.target_row.set_subtitle(str(folder / f"{stem}_YYYY-MM-DD_HHMMSS.wav"))
        self.target_row.set_tooltip_text(_("A start timestamp is added; an existing file is never overwritten."))
        self._free_checked = 0.0

    def _show_stats(self, seconds: float, size: int) -> None:
        self.timer.set_text(w.fmt_clock(seconds))
        self.size_value.set_text(format_bytes(size))
        w.set_pill(self.xrun_pill, str(self.xruns), "error" if self.xruns else "ok")
        self.xrun_pill.set_tooltip_text(_("Audio samples may be missing") if self.xruns else None)
        clipped = self.clipped or self.meter.any_clip()
        w.set_pill(self.clip_pill, _("Detected") if clipped else _("None"), "error" if clipped else "ok")

    def _update_free(self) -> None:
        folder = Path(self.folder_entry.get_text()).expanduser()
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        try:
            available = free_bytes(folder)
        except OSError:
            self.free_value.set_text("—")
            return
        self.free_value.set_text(format_bytes(available))
        hours = available / (48000 * 2 * 4) / 3600
        self.free_value.set_tooltip_text(_("About {hours:,.0f} h of 48 kHz/32-bit stereo").format(hours=hours))
        low = available < MIN_FREE_BYTES
        if low:
            self.free_value.add_css_class("error")
        else:
            self.free_value.remove_css_class("error")

    def _set_state_view(self) -> None:
        if self.process is not None:
            if self.stop_requested:
                text, kind = _("FINALIZING"), "warn"
            else:
                text, kind = _("RECORDING"), "rec"
        elif self._probing:
            text, kind = _("CHECKING"), "accent"
        elif self._outcome == "saved":
            text, kind = _("SAVED"), "ok"
        elif self._outcome == "failed":
            text, kind = _("FAILED"), "error"
        else:
            text, kind = _("READY"), "accent"
        w.set_pill(self.state_pill, text, kind)
        recording = self.process is not None and not self.stop_requested
        for widget in (self.hero, self.timer):
            if recording:
                widget.add_css_class("recording")
            else:
                widget.remove_css_class("recording")
        if self.process is not None:
            self.dock_status.set_text(_("Finalizing the WAV file…") if self.stop_requested
                                      else _("Recording to ") + (self.destination.name if self.destination else ""))
        elif self._probing:
            self.dock_status.set_text(_("Checking ") + self.profile.device + "…")
        elif self.completed_destination is not None:
            self.dock_status.set_text(_("Last take: ") + self.completed_destination.name)
        else:
            self.dock_status.set_text(_("Ready · ") + self.profile.device)

    def toggle_recording(self) -> None:
        """Ctrl+R: start, or request the normal finalizing stop."""
        if self.process is not None:
            if not self.stop_requested:
                self._stop(None)
        else:
            self._start(None)

    def _next_side(self) -> None:
        name = self.name_entry.get_text()
        match = re.search(r"^(.*?)(\d+)_Side([A-Z])$", name)
        if match:
            prefix, number, side = match.groups()
            if side == "A":
                name = f"{prefix}{number}_SideB"
            else:
                name = f"{prefix}{int(number) + 1:0{len(number)}d}_SideA"
        else:
            side = re.search(r"Side([A-Y])$", name)
            name = name[:-1] + chr(ord(side.group(1)) + 1) if side else name + "_SideB"
        self.name_entry.set_text(name)

    def _device_selected(
        self,
        dropdown: Gtk.DropDown,
        _parameter: object,
    ) -> None:
        if self.process:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.capture_devices):
            return
        device = self.capture_devices[selected]
        self.profile = CaptureProfile(device=device.pcm)
        self.device_chip.set_text(device.pcm)
        self.status.set_text(f"Capture device selected: {device.pcm}")

    def _refresh_devices(self, _button: Gtk.Button | None) -> None:
        if self.process:
            return
        selected_pcm = self.profile.device
        self.device_dropdown.set_sensitive(False)
        self.refresh_devices_button.set_sensitive(False)
        self.status.set_text("Scanning ALSA hardware capture devices…")
        threading.Thread(
            target=self._device_list_worker,
            args=(selected_pcm,),
            daemon=True,
        ).start()

    def _device_list_worker(self, selected_pcm: str) -> None:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        try:
            result = subprocess.run(
                host_command(["arecord", "-l"]),
                capture_output=True,
                timeout=5,
                env=environment,
            )
            detected = parse_capture_devices(
                result.stdout.decode(errors="replace")
            )
            devices = capture_devices_with_default(detected)
            if detected:
                message = f"Found {len(detected)} ALSA hardware capture device(s)."
            else:
                message = (
                    "No ALSA hardware capture devices were reported; "
                    "BlackmagicIO remains the configured default."
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            devices = capture_devices_with_default(())
            message = f"Could not list ALSA devices: {exc}"
        GLib.idle_add(
            self._device_list_done,
            devices,
            selected_pcm,
            message,
        )

    def _device_list_done(
        self,
        devices: tuple[CaptureDevice, ...],
        selected_pcm: str,
        message: str,
    ) -> bool:
        if self.process or self._disposed:
            return GLib.SOURCE_REMOVE
        self.capture_devices = list(devices)
        self.device_model = Gtk.StringList.new(
            [device.display_label for device in self.capture_devices]
        )
        self.device_dropdown.set_model(self.device_model)
        selected = next(
            (
                index
                for index, device in enumerate(self.capture_devices)
                if device.pcm == selected_pcm
            ),
            0,
        )
        self.device_dropdown.set_selected(selected)
        self._device_selected(self.device_dropdown, None)
        self.device_dropdown.set_sensitive(True)
        self.refresh_devices_button.set_sensitive(True)
        self.status.set_text(message)
        return GLib.SOURCE_REMOVE

    def _set_controls(self, recording: bool) -> None:
        self.probe_button.set_sensitive(not recording)
        self.device_dropdown.set_sensitive(not recording)
        self.refresh_devices_button.set_sensitive(not recording)
        self.record_button.set_sensitive(not recording)
        self.name_entry.set_sensitive(not recording)
        self.folder_entry.set_sensitive(not recording)
        self.browse_button.set_sensitive(not recording)
        self.stop_button.set_sensitive(recording)
        self.record_button.set_visible(not recording)
        self.stop_button.set_visible(recording)
        playable = (
            not recording
            and self.completed_destination is not None
            and self.completed_destination.is_file()
        )
        self.play_button.set_sensitive(playable)
        self.auto_stop_check.set_sensitive(not recording)
        settings_sensitive = not recording and self.auto_stop_check.get_active()
        self.auto_stop_earliest.set_sensitive(settings_sensitive)
        self.auto_stop_silence.set_sensitive(settings_sensitive)
        self.auto_stop_threshold.set_sensitive(settings_sensitive)
        self.disable_auto_stop_button.set_sensitive(
            recording and self.auto_stop_analyzer is not None
        )

    def _auto_stop_toggled(self, button: Gtk.CheckButton) -> None:
        if self.process:
            return
        enabled = button.get_active()
        self.auto_stop_earliest.set_sensitive(enabled)
        self.auto_stop_silence.set_sensitive(enabled)
        self.auto_stop_threshold.set_sensitive(enabled)
        self.auto_stop_status.set_text(
            "Auto-stop is enabled for the next recording."
            if enabled else "Auto-stop is off."
        )

    def _browse(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Choose recording folder")
        initial = Path(self.folder_entry.get_text()).expanduser()
        while not initial.exists() and initial != initial.parent:
            initial = initial.parent
        if initial.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(initial)))
        dialog.select_folder(self.window, None, self._folder_selected)

    def _folder_selected(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error as exc:
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self.status.set_text(f"Folder selection failed: {exc.message}")
            return
        path = folder.get_path()
        if path:
            self.folder_entry.set_text(path)
            self.status.set_text("Recording folder selected.")

    def _probe(self, _button: Gtk.Button) -> None:
        if self.process or self._probing or not self._capture_allowed():
            return
        self._probing = True
        self.probe_button.set_sensitive(False)
        self.record_button.set_sensitive(False)
        self.device_dropdown.set_sensitive(False)
        self.refresh_devices_button.set_sensitive(False)
        profile = self.profile
        self.status.set_text(f"Checking ALSA device {profile.device}…")
        threading.Thread(
            target=self._probe_worker,
            args=(profile,),
            daemon=True,
        ).start()

    def _probe_worker(self, profile: CaptureProfile) -> None:
        try:
            result = subprocess.run(host_command(profile.probe_command()), capture_output=True, timeout=5)
            detail = result.stderr.decode(errors="replace").strip().splitlines()
            message = f"{profile.device} supports the capture profile." if result.returncode == 0 else (detail[-1] if detail else f"{profile.device} could not be opened.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            message = f"Device check failed: {exc}"
        GLib.idle_add(self._probe_done, message)

    def _probe_done(self, message: str) -> bool:
        self._probing = False
        if self._disposed:
            return GLib.SOURCE_REMOVE
        self.status.set_text(message)
        self.probe_button.set_sensitive(True)
        self.record_button.set_sensitive(True)
        self.device_dropdown.set_sensitive(True)
        self.refresh_devices_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def _start(self, _button: Gtk.Button) -> None:
        if self.process or self._probing or not self._capture_allowed():
            return
        try:
            folder = ensure_directory(Path(self.folder_entry.get_text()))
        except OSError as exc:
            self.status.set_text(f"Could not create the recording folder: {exc}")
            return
        if not os.access(folder, os.W_OK):
            self.status.set_text("The recording folder is not writable.")
            return
        available = free_bytes(folder)
        if available < MIN_FREE_BYTES:
            self.status.set_text(f"Not enough free space: {format_bytes(available)} (at least 10 GiB required).")
            return
        destination = recording_path(folder, self.name_entry.get_text())
        if destination.exists():
            self.status.set_text("The destination already exists; nothing was overwritten.")
            return
        self._stop_playback()
        self.completed_destination = None
        try:
            self.process = BackendProcess(self.profile.command(destination))
        except OSError as exc:
            self.status.set_text(f"Could not start arecord: {exc}")
            return
        self.destination = destination
        self.stop_requested = False
        self.auto_stop_requested = False
        self.started_at = time.monotonic(); self.xruns = 0; self.clipped = False; self.meter_tail = ""
        self.last_vu = None
        self._outcome = None
        self.meter.reset()
        self.history.clear()
        self._xrun_counter = XrunCounter()
        self.file_label.set_text(str(destination))
        self.status.set_text("Recording directly from ALSA…")
        self._set_controls(True)
        if self.auto_stop_check.get_active():
            config = AutoStopConfig(
                earliest_seconds=self.auto_stop_earliest.get_value() * 60,
                silence_seconds=self.auto_stop_silence.get_value(),
                threshold_dbfs=self.auto_stop_threshold.get_value(),
            )
            self._start_auto_stop(destination, config)
        threading.Thread(
            target=self._monitor_process,
            args=(self.process,),
            daemon=True,
        ).start()

    def _start_auto_stop(self, destination: Path, config: AutoStopConfig) -> None:
        self._stop_auto_stop_analyzer()

        analyzer: GrowingWavAnalyzer

        def on_update(update: AnalysisUpdate) -> None:
            GLib.idle_add(self._handle_auto_stop_update, analyzer, update)

        def on_error(message: str) -> None:
            GLib.idle_add(self._handle_auto_stop_error, analyzer, message)

        analyzer = GrowingWavAnalyzer(
            destination,
            config,
            on_update,
            on_error,
            sample_rate=self.profile.rate,
        )
        self.auto_stop_analyzer = analyzer
        self.auto_stop_deadline = None
        self.auto_stop_status.set_text(
            "Auto-stop: waiting for tape activity; threshold "
            f"{config.threshold_dbfs:.0f} dBFS."
        )
        self.disable_auto_stop_button.set_sensitive(True)
        analyzer.start()

    def _handle_auto_stop_update(
        self,
        analyzer: GrowingWavAnalyzer,
        update: AnalysisUpdate,
    ) -> bool:
        if analyzer is not self.auto_stop_analyzer or not self.process:
            return GLib.SOURCE_REMOVE

        detector = update.detector
        config = analyzer.detector.config
        levels = (
            f"L {self._format_dbfs(update.left_dbfs)} · "
            f"R {self._format_dbfs(update.right_dbfs)}"
        )
        if detector.candidate_cancelled:
            self.auto_stop_deadline = None

        if detector.state == "waiting_for_activity":
            detail = "waiting for tape activity"
        elif detector.state == "waiting_for_window":
            minutes = config.earliest_seconds / 60
            detail = f"activity seen; detection starts at {minutes:g} min"
        elif detector.state == "listening":
            detail = "tape activity detected"
        elif detector.state == "silence":
            detail = (
                f"low activity {detector.silence_seconds:.0f}/"
                f"{config.silence_seconds:g} s"
            )
        else:
            if detector.candidate_started and self.auto_stop_deadline is None:
                self.auto_stop_deadline = (
                    time.monotonic() + AUTO_STOP_COUNTDOWN_SECONDS
                )
            remaining = self._auto_stop_countdown_remaining()
            detail = f"possible tape end; stopping in {remaining} s"

        self.auto_stop_status.set_text(f"Auto-stop: {detail} · {levels}")
        return GLib.SOURCE_REMOVE

    def _handle_auto_stop_error(
        self,
        analyzer: GrowingWavAnalyzer,
        message: str,
    ) -> bool:
        if analyzer is not self.auto_stop_analyzer:
            return GLib.SOURCE_REMOVE
        analyzer.stop()
        self.auto_stop_analyzer = None
        self.auto_stop_deadline = None
        self.disable_auto_stop_button.set_sensitive(False)
        self.auto_stop_status.set_text(
            f"Auto-stop disabled after an analysis error: {message}"
        )
        return GLib.SOURCE_REMOVE

    def _disable_auto_stop(self, _button: Gtk.Button) -> None:
        self._stop_auto_stop_analyzer()
        self.auto_stop_check.set_active(False)
        self.auto_stop_status.set_text(
            "Auto-stop was disabled; recording continues normally."
        )

    def _stop_auto_stop_analyzer(self) -> None:
        if self.auto_stop_analyzer:
            self.auto_stop_analyzer.stop()
            self.auto_stop_analyzer = None
        self.auto_stop_deadline = None
        self.disable_auto_stop_button.set_sensitive(False)

    @staticmethod
    def _format_dbfs(value: float) -> str:
        return "−∞ dBFS" if math.isinf(value) else f"{value:.1f} dBFS"

    def _auto_stop_countdown_remaining(self) -> int:
        if self.auto_stop_deadline is None:
            return AUTO_STOP_COUNTDOWN_SECONDS
        return max(0, math.ceil(self.auto_stop_deadline - time.monotonic()))

    def _monitor_process(self, process: subprocess.Popen[bytes]) -> None:
        def on_output(text: str) -> None:
            GLib.idle_add(self._handle_output, process, text)

        returncode, stderr_tail = drain_stderr_and_wait(process, on_output)
        GLib.idle_add(self._process_done, process, returncode, stderr_tail)

    def _handle_output(self, process: subprocess.Popen[bytes], text: str) -> bool:
        if process is not self.process:
            return GLib.SOURCE_REMOVE
        combined = self.meter_tail + text
        self.meter_tail = combined[-256:]
        vu = parse_vu(combined)
        if vu:
            self.last_vu = tuple(vu)
            self._last_db = [percent_to_dbfs(percent) for percent in vu]
            self.meter.set_levels(*self._last_db)
            self.clipped |= any(percent >= 100 for percent in vu)
        self.xruns += self._xrun_counter.feed(text)
        return GLib.SOURCE_REMOVE

    def _stop(self, _button: Gtk.Button) -> None:
        self._begin_stop(auto_stop_requested=False)

    def _begin_stop(self, *, auto_stop_requested: bool) -> None:
        if self.process and self.process.poll() is None:
            self._stop_auto_stop_analyzer()
            self.stop_button.set_sensitive(False)
            self.status.set_text(
                "Tape-end condition sustained; stopping and finalizing the WAV file…"
                if auto_stop_requested
                else "Stopping and finalizing the WAV file…"
            )
            try:
                self.process.interrupt()
            except (OSError, BrokenPipeError) as error:
                self.stop_button.set_sensitive(True)
                self.status.set_text(f"Stop request failed: {error}; recording is still monitored.")
                return
            self.stop_requested = True
            self.auto_stop_requested = auto_stop_requested

    def _process_done(
        self,
        process: subprocess.Popen[bytes],
        returncode: int,
        stderr: str,
    ) -> bool:
        if process is not self.process:
            return GLib.SOURCE_REMOVE
        auto_stop_was_requested = self.auto_stop_requested
        self.xruns += self._xrun_counter.finish()
        self._stop_auto_stop_analyzer()
        if auto_stop_was_requested:
            self.auto_stop_status.set_text("Auto-stop: recording ended.")
        stopped_cleanly = capture_exit_was_clean(
            returncode,
            self.stop_requested,
        )
        completed_file = (
            self.destination
            if self.destination and self.destination.is_file()
            else None
        )
        if stopped_cleanly and completed_file:
            self.completed_destination = completed_file
            self._outcome = "saved"
            self.status.set_text("Recording saved." + (f" WARNING: {self.xruns} XRUN(s); audio samples may be missing." if self.xruns else "") + (" CLIPPING was detected." if self.clipped else ""))
            w.toast(self, _("Recording saved · ") + completed_file.name, button=_("Next Side"),
                    callback=self._next_side, timeout=6)
        elif stopped_cleanly:
            self._outcome = "failed"
            self.status.set_text("Recording failed: the completed WAV file is missing.")
        else:
            self._outcome = "failed"
            detail = capture_error_detail(stderr, returncode)
            message = f"Recording failed: {detail}"
            if completed_file:
                message += " The partial WAV was preserved."
            self.status.set_text(message)
        self.process = None
        size = completed_file.stat().st_size if completed_file else 0
        self._show_stats(time.monotonic() - self.started_at, size)
        self.meter.silence()
        self.stop_requested = False
        self.auto_stop_requested = False
        self._set_controls(False)
        self._set_state_view()
        return GLib.SOURCE_REMOVE

    def _play(self, _button: Gtk.Button) -> None:
        if not self.completed_destination or not self.completed_destination.is_file():
            self.play_button.set_sensitive(False)
            self.status.set_text("No completed recording is available for playback.")
            return
        if self.media and self.media.get_playing():
            self.media.pause()
            w.set_button_label(self.play_button, _("Play"), "media-playback-start-symbolic")
            self.status.set_text("Playback paused.")
            return
        if self.media is None:
            self.media = Gtk.MediaFile.new_for_filename(str(self.completed_destination))
            self.media.connect("notify::ended", self._media_state_changed)
            self.media.connect("notify::error", self._media_state_changed)
        self.media.play()
        w.set_button_label(self.play_button, _("Pause"), "media-playback-pause-symbolic")
        self.status.set_text("Playing the completed recording…")

    def _media_state_changed(self, media: Gtk.MediaFile, _parameter: object) -> None:
        error = media.get_error()
        if error:
            w.set_button_label(self.play_button, _("Play"), "media-playback-start-symbolic")
            self.status.set_text(f"Playback failed: {error.message}")
        elif media.get_ended():
            w.set_button_label(self.play_button, _("Play"), "media-playback-start-symbolic")
            self.status.set_text("Playback finished.")

    def _stop_playback(self) -> None:
        if self.media:
            self.media.pause()
            self.media.clear()
            self.media = None
        w.set_button_label(self.play_button, _("Play"), "media-playback-start-symbolic")

    def _tick(self) -> bool:
        if self.auto_stop_deadline is not None and self.process:
            remaining = self._auto_stop_countdown_remaining()
            if remaining <= 0:
                self._begin_stop(auto_stop_requested=True)
            else:
                self.auto_stop_status.set_text(
                    "Auto-stop: possible tape end; "
                    f"stopping in {remaining} s. Use Disable auto-stop to cancel."
                )
        if self.process:
            size = self.destination.stat().st_size if self.destination and self.destination.exists() else 0
            self._show_stats(time.monotonic() - self.started_at, size)
            self.history.push(*self._last_db)
        now = time.monotonic()
        if now - self._free_checked > (2 if self.process else 10):
            self._free_checked = now
            self._update_free()
        self._set_state_view()
        return GLib.SOURCE_CONTINUE

    @property
    def running(self):
        # Stay busy through stderr drain and GUI completion, even after OS exit.
        return self.process is not None or self._probing

    def _capture_allowed(self):
        blocker = self.jobs.capture_blocker("Audio recording")
        if blocker:
            self.status.set_text(f"Stop {blocker} before opening the audio device.")
            return False
        return True

    def shutdown(self):
        if self.running:
            raise RuntimeError("Audio recording/probe must finish before closing")
        self._disposed = True
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        self._stop_auto_stop_analyzer()
        self._stop_playback()
