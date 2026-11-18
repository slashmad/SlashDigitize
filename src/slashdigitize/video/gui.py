"""Main window: grouped workflow sidebar, session state, toasts and close guard."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from slashdigitize.audio.app import RecorderPage, format_bytes  # noqa: E402
from slashdigitize.jobs import JobRegistry  # noqa: E402
from slashdigitize.shell import WorkflowTab  # noqa: E402
from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.video.capture import CapturePage  # noqa: E402
from slashdigitize.video.edit import EditPage  # noqa: E402
from slashdigitize.video.ffmpeg import detect_ffmpeg, detect_renderers, list_encoders, list_pixel_formats  # noqa: E402
from slashdigitize.video.help_page import HelpPage  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402
from slashdigitize.video.system_page import SystemPage  # noqa: E402
from slashdigitize.video.timelapse_page import TimelapsePage  # noqa: E402
from slashdigitize.video.vapoursynth_page import VapourSynthPage  # noqa: E402
from slashdigitize.video.vapoursynth_process import VapourSynthProcessPage  # noqa: E402

APP_ICON = "se.slashmad.SlashDigitize"
VERSION = "0.1.0"

# (stack name, title, header subtitle, icon); grouped into sidebar sections.
SECTIONS = [
    (_("Capture"), [
        ("audio", _("Audio recording"), _("Direct ALSA · 48 kHz · 32-bit stereo"), "sd-audio-symbolic"),
        ("capture", _("Video capture"), _("V4L2 · FFmpeg · live view"), "sd-video-symbolic"),
    ]),
    (_("Process"), [
        ("trim", _("Trim & export"), _("Cut, correct and export"), "sd-trim-symbolic"),
        ("timelapse", _("Timelapse"), _("Images to video"), "sd-timelapse-symbolic"),
        ("vapoursynth", _("VapourSynth"), _("Deinterlace and clean up"), "sd-vapoursynth-symbolic"),
    ]),
    (_("System"), [
        ("vsrepo", _("Filter plugins"), _("VSRepo · VapourSynth packages"), "sd-plugins-symbolic"),
        ("hardware", _("System & codecs"), _("What this machine can encode"), "sd-system-symbolic"),
        ("help", _("Help"), _("Workflows, safety and shortcuts"), "sd-help-symbolic"),
    ]),
]
PAGES = {name: (title, subtitle) for _s, items in SECTIONS for name, title, subtitle, _i in items}


class NavRow(Gtk.ListBoxRow):
    def __init__(self, name: str, title: str, icon: str, section: str, first: bool):
        super().__init__()
        self.name = name
        self.section = section
        self.first_in_section = first
        box = Gtk.Box(spacing=12)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=title, xalign=0, hexpand=True))
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER, visible=False)
        self.dot.add_css_class("sd-nav-dot")
        box.append(self.dot)
        self.set_child(box)
        self.set_tooltip_text(title)

    def set_state(self, state: str | None) -> None:
        self.dot.set_visible(state is not None)
        if state == "recording":
            self.dot.remove_css_class("busy")
        else:
            self.dot.add_css_class("busy")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="SlashDigitize")
        self.set_icon_name(APP_ICON)
        self.set_default_size(1380, 900)
        self._closed = False
        self._refreshing = False
        self._close_dialog: Adw.AlertDialog | None = None
        self._since: dict[tuple[str, str], float] = {}
        self._ffmpeg_command: list[str] | None = None
        self._encoders: list = []
        self._pixel_formats: list = []
        self._hardware_info = None

        self.jobs = JobRegistry()
        self.audio_page = WorkflowTab(lambda: RecorderPage(self, self.jobs), audio=True)
        self.capture_page = WorkflowTab(lambda: CapturePage(self.jobs))
        self.edit_page = WorkflowTab(EditPage)
        self.timelapse_page = WorkflowTab(TimelapsePage)
        self.vapoursynth_process_page = WorkflowTab(VapourSynthProcessPage)
        self.vapoursynth_page = WorkflowTab(VapourSynthPage)
        self.system_page = SystemPage(self.on_refresh_clicked)
        self.help_page = HelpPage(self.navigate)
        tabs = {
            "audio": self.audio_page, "capture": self.capture_page, "trim": self.edit_page,
            "timelapse": self.timelapse_page, "vapoursynth": self.vapoursynth_process_page,
            "vsrepo": self.vapoursynth_page, "hardware": self.system_page, "help": self.help_page,
        }
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=140,
                               hexpand=True, vexpand=True, hhomogeneous=False, vhomogeneous=False)
        for name, widget in tabs.items():
            self.stack.add_titled(widget, name, PAGES[name][0])

        self.jobs.register("Audio recording", lambda: bool(self.audio_page.widget and self.audio_page.widget.running),
                           capture=True)
        self.jobs.register("Video capture / monitor", lambda: bool(self.capture_page.widget and (
            self.capture_page.widget.capture_runner.running or self.capture_page.widget._preview_running)),
            capture=True)
        self.jobs.register("Timelapse", lambda: bool(self.timelapse_page.widget and self.timelapse_page.widget.running))
        self.jobs.register("Trim & export", lambda: bool(self.edit_page.widget and self.edit_page.widget.runner.running))
        self.jobs.register("VapourSynth", lambda: bool(self.vapoursynth_process_page.widget and (
            self.vapoursynth_process_page.widget.runner.running
            or self.vapoursynth_process_page.widget._queue_running)))

        self._build_shell(app)
        self.connect("close-request", self.on_close_request)
        self.stack.connect("notify::visible-child", self._on_stack_changed)
        self.navigate("audio")
        self._on_stack_changed()
        self._status_timer = GLib.timeout_add(250, self._update_job_status)
        self.refresh()

    # ------------------------------------------------------------------ shell
    def _build_shell(self, app: Gtk.Application) -> None:
        self.title_widget = Adw.WindowTitle()
        header = Adw.HeaderBar(title_widget=self.title_widget)
        self.sidebar_toggle = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", active=True,
                                               tooltip_text=_("Show workflows (F9)"))
        header.pack_start(self.sidebar_toggle)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Rescan Capabilities"), "win.rescan")
        section.append(_("Keyboard Shortcuts"), "win.shortcuts")
        section.append(_("About SlashDigitize"), "win.about")
        menu.append_section(None, section)
        end = Gio.Menu()
        end.append(_("Close Window"), "win.close")
        end.append(_("Quit"), "app.quit")
        menu.append_section(None, end)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text=_("Main menu")))

        self.rec_button = Gtk.Button(visible=False, valign=Gtk.Align.CENTER,
                                     tooltip_text=_("Go to the active recording"))
        self.rec_button.add_css_class("sd-rec-pill")
        rec_box = Gtk.Box(spacing=8)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("sd-rec-dot")
        rec_box.append(dot)
        self.rec_label = Gtk.Label(label="REC 00:00:00")
        rec_box.append(self.rec_label)
        self.rec_button.set_child(rec_box)
        self.rec_button.connect("clicked", lambda *_: self.navigate(self._rec_page or "audio"))
        header.pack_end(self.rec_button)
        self.job_spinner = Adw.Spinner(visible=False)
        header.pack_end(self.job_spinner)

        content = Adw.ToolbarView(content=self.stack)
        content.add_top_bar(header)

        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self.nav.add_css_class("sd-nav")
        self.rows: dict[str, NavRow] = {}
        for section_title, items in SECTIONS:
            for index, (name, title, _sub, icon) in enumerate(items):
                row = NavRow(name, title, icon, section_title, index == 0)
                self.rows[name] = row
                self.nav.append(row)
        self.nav.set_header_func(self._nav_header)
        self.nav.connect("row-selected", self._on_nav)
        nav_scroll = Gtk.ScrolledWindow(vexpand=True)
        nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_scroll.set_child(self.nav)

        self.session_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.session_card.add_css_class("sd-session")
        self.session_title = w.label(_("Idle"), css=("sd-session-title",))
        self.session_sub = w.label(_("Nothing running"), css=("sd-session-sub",), wrap=True)
        self.disk_label = w.label("", css=("sd-session-sub",), ellipsize=True)
        for widget in (self.session_title, self.session_sub, self.disk_label):
            self.session_card.append(widget)
        # Kept for callers of the former status line: the session summary.
        self.shell_status = self.session_sub

        side_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_body.append(nav_scroll)
        side_body.append(self.session_card)
        brand = Gtk.Box(spacing=10)
        icon = Gtk.Image.new_from_icon_name(APP_ICON)
        icon.set_pixel_size(26)
        brand.append(icon)
        brand_label = Gtk.Label(label="SlashDigitize")
        brand_label.add_css_class("sd-brand-title")
        brand.append(brand_label)
        sidebar = Adw.ToolbarView(content=side_body)
        sidebar.add_top_bar(Adw.HeaderBar(title_widget=brand, show_end_title_buttons=False))
        sidebar.add_css_class("sd-sidebar")

        self.split = Adw.OverlaySplitView(sidebar=sidebar, content=content, min_sidebar_width=220,
                                         max_sidebar_width=260, sidebar_width_fraction=0.2)
        self.sidebar_toggle.bind_property("active", self.split, "show-sidebar",
                                          GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 860sp"))
        compact.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(compact)

        for name, callback in [("about", self._show_about), ("shortcuts", self._show_shortcuts),
                               ("close", self.close), ("rescan", lambda: self.on_refresh_clicked()),
                               ("record", self._record_shortcut),
                               ("toggle-sidebar", lambda: self.sidebar_toggle.set_active(
                                   not self.sidebar_toggle.get_active()))]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, cb=callback: cb())
            self.add_action(action)
        go = Gio.SimpleAction.new("go", GLib.VariantType.new("s"))
        go.connect("activate", lambda _a, value: self.navigate(value.get_string()))
        self.add_action(go)
        app.set_accels_for_action("win.toggle-sidebar", ["F9"])
        app.set_accels_for_action("win.shortcuts", ["<Primary>question"])
        app.set_accels_for_action("win.record", ["<Primary>r"])
        for index, name in enumerate(self.rows, start=1):
            app.set_accels_for_action(f"win.go::{name}", [f"<Alt>{index}"])
        self._rec_page: str | None = None

    def _nav_header(self, row: NavRow, _before) -> None:
        if row.first_in_section:
            header = Gtk.Label(label=row.section.upper(), xalign=0)
            header.add_css_class("sd-nav-section")
            row.set_header(header)
        else:
            row.set_header(None)

    def _on_nav(self, _box, row) -> None:
        if row is not None and self.stack.get_visible_child_name() != row.name:
            self.stack.set_visible_child_name(row.name)

    def _on_stack_changed(self, *_args) -> None:
        name = self.stack.get_visible_child_name()
        child = self.stack.get_visible_child()
        if isinstance(child, WorkflowTab):
            child.activate()
        row = self.rows.get(name)
        if row is not None and self.nav.get_selected_row() is not row:
            self.nav.select_row(row)
        title, subtitle = PAGES.get(name, ("SlashDigitize", ""))
        self.title_widget.set_title(title)
        self.title_widget.set_subtitle(subtitle)
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def navigate(self, name: str) -> None:
        if name in self.rows:
            self.stack.set_visible_child_name(name)

    # Former name of the tab activation hook, kept for tests and callers.
    _activate_tab = _on_stack_changed

    def toast(self, text: str, button: str | None = None, callback=None, timeout: int = 3) -> None:
        toast = Adw.Toast(title=text, timeout=timeout)
        toast.set_use_markup(False)
        if button and callback:
            toast.set_button_label(button)
            toast.connect("button-clicked", lambda *_: callback())
        self.toasts.add_toast(toast)

    def _record_shortcut(self) -> None:
        page = self.audio_page.widget
        if page is None or self.stack.get_visible_child_name() != "audio":
            return
        page.toggle_recording()

    # ------------------------------------------------------- session state
    def activities(self) -> list[tuple[str, str, str]]:
        """(page, label, state) for everything running; REC only for
        actual captures, never for probes, live view, finalization or exports."""
        found: list[tuple[str, str, str]] = []
        audio = self.audio_page.widget
        if audio is not None:
            if audio.process is not None:
                found.append(("audio", _("Audio recording"),
                              "finalizing" if audio.stop_requested else "recording"))
            elif audio._probing:
                found.append(("audio", _("Audio device check"), "checking"))
        capture = self.capture_page.widget
        if capture is not None:
            if capture.capture_runner.running:
                found.append(("capture", _("Video capture"), "recording"))
            if capture._preview_running:
                found.append(("capture", _("Live view"), "monitoring"))
        timelapse = self.timelapse_page.widget
        if timelapse is not None and timelapse.running:
            found.append(("timelapse", _("Timelapse render"), "rendering"))
        edit = self.edit_page.widget
        if edit is not None and edit.runner.running:
            found.append(("trim", _("Trim export"), "exporting"))
        vs = self.vapoursynth_process_page.widget
        if vs is not None and (vs.runner.running or vs._queue_running):
            found.append(("vapoursynth", _("VapourSynth export"), "exporting"))
        return found

    def _elapsed(self, key: tuple[str, str]) -> str:
        audio = self.audio_page.widget
        if key[0] == "audio" and audio is not None and audio.process is not None:
            return w.fmt_clock(time.monotonic() - audio.started_at)
        return w.fmt_clock(time.monotonic() - self._since.get(key, time.monotonic()))

    def _update_job_status(self):
        if self._closed:
            return GLib.SOURCE_REMOVE
        activities = self.activities()
        now = time.monotonic()
        keys = {(page, label) for page, label, _s in activities}
        for key in keys:
            self._since.setdefault(key, now)
        for key in list(self._since):
            if key not in keys:
                del self._since[key]

        states: dict[str, str] = {}
        recording = None
        for page, label, state in activities:
            if state == "recording":
                states[page] = "recording"
                recording = recording or (page, label)
            else:
                states.setdefault(page, state)
        for name, row in self.rows.items():
            row.set_state(states.get(name))
        self._rec_page = recording[0] if recording else None
        self.rec_button.set_visible(recording is not None)
        others = [(label, state) for page, label, state in activities if state != "recording"]
        self.job_spinner.set_visible(bool(others))
        self.job_spinner.set_tooltip_text("\n".join(f"{label} — {state}" for label, state in others) or None)

        active = self.jobs.active()  # authoritative; includes any registered job
        if not active and self._close_dialog is not None:
            # Everything finished: the close warning no longer applies.
            self._close_dialog.force_close()
            self._close_dialog = None
        if recording:
            elapsed = self._elapsed(recording)
            self.rec_label.set_text(f"REC {elapsed}")
            self.session_card.add_css_class("recording")
            self.session_title.set_text(_("Recording"))
        else:
            self.session_card.remove_css_class("recording")
            if activities:
                self.session_title.set_text(activities[0][2].capitalize())
            elif active:
                self.session_title.set_text(_("Busy"))
            elif self._refreshing:
                self.session_title.set_text(_("Scanning"))
            else:
                self.session_title.set_text(_("Idle"))
        if active:
            self.session_sub.set_text(_("Running: ") + ", ".join(active))
        elif self._refreshing:
            self.session_sub.set_text(_("Checking FFmpeg capabilities…"))
        else:
            self.session_sub.set_text(_("Nothing running"))
        if int(now * 4) % 20 == 0 or not self.disk_label.get_text():
            self._update_disk()
        return GLib.SOURCE_CONTINUE

    def _update_disk(self) -> None:
        audio = self.audio_page.widget
        folder = Path(audio.folder_entry.get_text()).expanduser() if audio is not None else Path.home() / "Music"
        probe = folder
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            import shutil
            free = shutil.disk_usage(probe).free
            home = str(Path.home())
            shown = str(folder).replace(home, "~", 1) if str(folder).startswith(home) else str(folder)
            self.disk_label.set_text(f"{shown} · {format_bytes(free)} " + _("free"))
        except OSError:
            self.disk_label.set_text("")

    # ------------------------------------------------------------- dialogs
    def _show_about(self) -> None:
        dialog = Adw.AboutDialog(application_name="SlashDigitize", version=VERSION, application_icon=APP_ICON,
                                 developer_name="slashmad", license_type=Gtk.License.GPL_3_0,
                                 comments=_("Audio and video digitization with arecord, FFmpeg and VapourSynth"))
        dialog.present(self)

    def _show_shortcuts(self) -> None:
        sections = [
            (_("General"), [(_("Show or hide workflows"), "F9"), (_("Keyboard shortcuts"), "<Primary>question"),
                            (_("Quit"), "<Primary>q")]),
            (_("Workflows"), [(PAGES[name][0], f"<Alt>{index}") for index, name in enumerate(self.rows, start=1)]),
            (_("Audio recording"), [(_("Record / Stop (on the Audio page)"), "<Primary>r")]),
        ]
        if hasattr(Adw, "ShortcutsDialog"):
            dialog = Adw.ShortcutsDialog()
            for heading, items in sections:
                section = Adw.ShortcutsSection(title=heading)
                for title, accel in items:
                    section.add(Adw.ShortcutsItem(title=title, accelerator=accel))
                dialog.add(section)
            dialog.present(self)
            return
        # libadwaita 1.7 fallback (e.g. Debian 13 Trixie) before Adw.ShortcutsDialog (1.8).
        page = Adw.PreferencesPage()
        for heading, items in sections:
            group = Adw.PreferencesGroup(title=heading)
            for title, accel in items:
                row = Adw.ActionRow(title=title, use_markup=False)
                row.add_suffix(Gtk.ShortcutLabel(accelerator=accel, valign=Gtk.Align.CENTER))
                group.add(row)
            page.add(group)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        Adw.Dialog(title=_("Keyboard shortcuts"), child=view, content_width=460, content_height=520).present(self)

    # --------------------------------------------------------- capabilities
    def on_refresh_clicked(self, *_args) -> None:
        self.refresh()

    def refresh(self) -> None:
        if self._refreshing or self._closed:
            return
        self._refreshing = True
        self.system_page.set_scanning(True)

        def worker():
            try:
                info = detect_ffmpeg()
                statuses, hardware = detect_renderers(info)
                data = info, statuses, hardware, list_encoders(), list_pixel_formats()
                GLib.idle_add(self._finish_refresh, data, None)
            except Exception as error:  # noqa: BLE001 - shown to the user
                GLib.idle_add(self._finish_refresh, None, str(error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, data, error):
        if self._closed:
            return GLib.SOURCE_REMOVE
        self._refreshing = False
        if error:
            self.system_page.show_error(error)
            self.toast(_("Capability check failed"))
            return GLib.SOURCE_REMOVE
        info, statuses, hardware, encoders, pixel_formats = data
        self._ffmpeg_command = info.command
        self._encoders = encoders
        self._pixel_formats = pixel_formats
        self._hardware_info = hardware
        self.system_page.update(info, statuses, hardware, encoders)
        common = dict(ffmpeg_command=self._ffmpeg_command, encoders=self._encoders)
        self.capture_page.sync_capabilities(**common, pixel_formats=pixel_formats, hardware_info=hardware)
        self.edit_page.sync_capabilities(**common, pixel_formats=pixel_formats, hardware_info=hardware)
        self.timelapse_page.sync_capabilities(**common, pixel_formats=pixel_formats, hardware_info=hardware)
        self.vapoursynth_process_page.sync_capabilities(**common, pixel_formats=pixel_formats)
        self.vapoursynth_page.sync_capabilities(**common, hardware_info=hardware)
        if info.command is None:
            self.toast(_("FFmpeg not found. Install it or ensure it is in PATH."), timeout=6)
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------- close guard
    def on_close_request(self, _window) -> bool:
        active = self.jobs.active()
        if active:
            self.session_sub.set_text(_("Running: ") + ", ".join(active))
            if self._close_dialog is None:
                dialog = Adw.AlertDialog(
                    heading=_("Work in progress"),
                    body=_("Stop these and wait for them to finish before closing, so files are finalized:")
                    + "\n\n• " + "\n• ".join(active))
                dialog.add_response("ok", _("Keep Working"))
                dialog.set_default_response("ok")
                dialog.connect("response", lambda *_: setattr(self, "_close_dialog", None))
                self._close_dialog = dialog
                dialog.present(self)
            return True
        self._closed = True
        GLib.source_remove(self._status_timer)
        for tab in [self.audio_page, self.capture_page, self.edit_page, self.timelapse_page,
                    self.vapoursynth_process_page, self.vapoursynth_page]:
            tab.shutdown()
        return False
