"""Layout of the video capture page (replaces capture_page.ui).

Widget names match the former GtkBuilder ids, so CapturePage logic binds to
them unchanged through ``Layout.get_object``."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.ui.rows import ChoiceRow, EntryRow, PathRow, SpinRow, SwitchRow  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402


class RowSubtitle:
    """Label-like ``set_text``/``get_text`` writing a row subtitle."""

    def __init__(self, row):
        self.row = row

    def set_text(self, text: str) -> None:
        self.row.set_subtitle(text or "")

    def get_text(self) -> str:
        return self.row.get_subtitle() or ""

    def set_visible(self, _visible: bool) -> None:
        pass  # the row stays; an empty subtitle simply disappears

    def __getattr__(self, name):
        return getattr(self.row, name)  # tooltips, sensitivity, …


def build() -> w.Layout:
    L = w.Layout()

    # ---------------------------------------------------------------- preview
    picture = L.add("preview_picture", Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN,
                                                   hexpand=True, vexpand=True))
    picture.set_size_request(320, 240)
    overlay = Gtk.Overlay(child=picture)
    placeholder = Adw.StatusPage(icon_name="sd-video-symbolic", title=_("No live view"),
                                 description=_("Start the live view to check picture and sound before capturing."))
    placeholder.add_css_class("compact")
    overlay.add_overlay(L.add("preview_placeholder", placeholder))
    rec_chip = Gtk.Label(label="● REC", halign=Gtk.Align.START, valign=Gtk.Align.START, visible=False)
    rec_chip.add_css_class("sd-overlay-chip")
    rec_chip.add_css_class("rec")
    overlay.add_overlay(L.add("preview_rec_chip", rec_chip))
    frame = Gtk.AspectFrame(ratio=4 / 3, obey_child=False, child=overlay)
    frame.add_css_class("sd-preview")
    frame.set_overflow(Gtk.Overflow.HIDDEN)

    start = L.add("preview_start_button", w.label_button(_("Live View"), "media-playback-start-symbolic",
                                                         css=("pill",)))
    stop = L.add("preview_stop_button", w.label_button(_("Stop"), "media-playback-stop-symbolic",
                                                       css=("pill",)))
    stop.set_sensitive(False)
    mute = L.add("preview_mute_check", Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic",
                                                        tooltip_text=_("Mute live audio"),
                                                        valign=Gtk.Align.CENTER))
    mute.add_css_class("flat")
    volume = L.add("preview_volume_scale", w.scale(0.0, 2.0, 0.01, 1.0, width=120))
    volume.set_tooltip_text(_("Live audio volume"))
    transport = w.hbox(start, stop, mute, volume, spacing=8)
    meter = L.add("preview_meter", w.StereoMeter(compact=True))
    meter.set_tooltip_text(_("Live audio level (RMS)"))
    status = L.add("preview_status_label", w.label("", css=("sd-meta",), wrap=True))
    info = L.add("capture_info_label", w.label(_("Waiting for FFmpeg capability scan..."),
                                               css=("sd-meta",), wrap=True))
    live = w.group()
    live.add(L.add("live_during_capture_combo", ChoiceRow(_("Live view during capture"))))
    preview_col = w.vbox(frame, transport, meter, status, live, info, spacing=12)

    # --------------------------------------------------------------- settings
    refresh = L.add("refresh_devices_button", w.icon_button("view-refresh-symbolic",
                                                            _("Rescan video and audio devices")))
    source = w.group(_("Source"), suffix=refresh)
    profile = L.add("profile_combo", ChoiceRow(_("Profile")))
    apply_profile = L.add("apply_profile_button", w.label_button(_("Apply"), None, css=("flat",)))
    profile.add_suffix(apply_profile)
    L.add("profile_info_label", RowSubtitle(profile))
    source.add(profile)
    source.add(L.add("video_device_combo", ChoiceRow(_("Video device"))))
    source.add(L.add("video_input_combo", ChoiceRow(_("Video input"))))
    source.add(L.add("audio_source_combo", ChoiceRow(_("Audio source"))))
    source.add(L.add("audio_backend_combo", ChoiceRow(_("Audio backend"))))
    hint = L.add("device_hint_label", w.notice())
    source_box = w.vbox(source, hint, spacing=8)

    signal = w.group(_("Signal"))
    signal.add(L.add("video_standard_combo", ChoiceRow(_("TV standard"))))
    signal.add(L.add("video_format_combo", ChoiceRow(_("Input format"))))
    signal.add(L.add("video_size_combo", ChoiceRow(_("Video size"))))
    signal.add(L.add("video_size_entry", EntryRow(_("Custom size"), placeholder="720x576")))
    signal.add(L.add("use_libv4l2_check", SwitchRow(_("Use libv4l2"), _("Format conversion in user space"),
                                                    active=True)))

    output = w.group(_("Output"))
    out = L.add("output_entry", PathRow(_("Output file"), tooltip=_("Choose output file")))
    L.add("output_browse_button", out.button)
    output.add(out)
    output.add(L.add("container_combo", ChoiceRow(_("Container"))))
    output.add(L.add("capture_video_codec_combo", ChoiceRow(_("Video codec"))))
    output.add(L.add("show_all_capture_codecs", SwitchRow(_("Show codecs without hardware"))))
    output.add(L.add("capture_video_bitrate_entry", EntryRow(_("Video bitrate"), "6M", placeholder="6M")))
    output.add(L.add("capture_preset_combo", ChoiceRow(_("Preset"))))

    audio = w.group(_("Audio"))
    audio.add(L.add("capture_audio_codec_combo", ChoiceRow(_("Audio codec"))))
    audio.add(L.add("capture_audio_bitrate_entry", EntryRow(_("Audio bitrate"), "192k", placeholder="192k")))
    audio.add(L.add("sample_rate_spin", SpinRow(_("Sample rate"), 8000, 192000, 1000, 48000, subtitle="Hz")))
    audio.add(L.add("channels_combo", ChoiceRow(_("Channels"))))
    audio.add(L.add("audio_filter_combo", ChoiceRow(_("Cleanup"))))
    audio.add(L.add("audio_gain_spin", SpinRow(_("Gain"), -24.0, 24.0, 0.5, 0.0, digits=1, subtitle="dB")))

    advanced_group = w.group()
    advanced = Adw.ExpanderRow(title=_("Advanced"),
                               subtitle=_("Pixel format, frame rate, deinterlacing, tune, extra arguments"))
    advanced.add_prefix(Gtk.Image.new_from_icon_name("preferences-other-symbolic"))
    advanced.add_row(L.add("capture_pixfmt_combo", ChoiceRow(_("Pixel format"))))
    advanced.add_row(L.add("match_fps_check", SwitchRow(_("Match source frame rate"), active=True)))
    fps = L.add("output_fps_spin", SpinRow(_("Output frame rate"), 1, 120, 0.01, 25.0, digits=3, page=1.0))
    fps.set_sensitive(False)
    advanced.add_row(fps)
    advanced.add_row(L.add("deinterlace_check", SwitchRow(_("Deinterlace"), "yadif")))
    advanced.add_row(L.add("capture_tune_entry", EntryRow(_("Tune"), placeholder=_("optional"))))
    advanced.add_row(L.add("capture_extra_entry", EntryRow(_("Extra FFmpeg arguments"),
                                                           placeholder=_("optional"))))
    advanced_group.add(advanced)

    stop_group = w.group(_("Stop automatically"))
    stop_group.add(L.add("capture_auto_stop_check", SwitchRow(_("Stop after a fixed duration"),
                                                              _("Useful for unattended tapes"))))
    stop_group.add(L.add("capture_auto_stop_hours_spin", SpinRow(_("Hours"), 0, 72, 1, 0)))
    stop_group.add(L.add("capture_auto_stop_minutes_spin", SpinRow(_("Minutes"), 0, 59, 1, 0, page=5)))
    countdown = L.add("capture_auto_stop_countdown_label", w.label("", css=("sd-meta",), xalign=0))
    countdown.set_visible(False)

    settings_col = w.vbox(source_box, signal, output, audio, advanced_group,
                          w.vbox(stop_group, countdown, spacing=8), spacing=22)

    status_label = L.add("capture_status_label", w.notice("sd-notice"))
    command, buffer, _view = w.code_view("", "sh", title=_("Capture command"), min_height=60)
    L.add("capture_command_buffer", buffer)
    columns = w.columns(preview_col, settings_col, spacing=24)
    content = w.vbox(status_label, columns, command, spacing=22)

    log_scroller, log_view = w.log_view()
    L.add("capture_log_view", log_view)
    L.add("capture_log_dialog", w.TextDialog(_("Capture log"), log_scroller))

    dock_status = L.add("capture_dock_status", w.dock_status())
    log_button = L.add("capture_log_button", w.label_button(_("Log"), "utilities-terminal-symbolic",
                                                            css=("pill", "flat")))
    start_capture = L.add("capture_start_button", w.label_button(_("Start Capture"), "media-record-symbolic",
                                                                 css=("sd-record",)))
    stop_capture = L.add("capture_stop_button", w.label_button(_("Stop Capture"), "media-playback-stop-symbolic",
                                                               css=("sd-record", "stop")))
    stop_capture.set_sensitive(False)
    stop_capture.set_visible(False)
    banner = Adw.Banner(title=_("FFmpeg was not found — capture is unavailable until it is installed."))
    L.add("capture_banner", banner)
    L.add("capture_page_root", w.page_view(content, w.dock(dock_status, log_button, start_capture, stop_capture),
                                           banner=banner, max_width=1400))
    return L
