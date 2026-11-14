"""Layout of the Trim & export page (replaces edit_page.ui).

Widget names match the former GtkBuilder ids, so EditPage logic binds to
them unchanged through ``Layout.get_object``."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.ui.rows import ChoiceRow, EntryRow, PathRow, SpinRow, SwitchRow  # noqa: E402
from slashdigitize.video.capture_layout import RowSubtitle  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402

NUDGES = [(-100, "−100"), (-10, "−10"), (-5, "−5"), (-1, "−1"), (1, "+1"), (5, "+5"), (10, "+10"), (100, "+100")]
NUDGE_NAMES = {-100: "prev_100_frames", -10: "prev_10_frames", -5: "prev_5_frames", -1: "prev_frame",
               1: "next_frame", 5: "next_5_frames", 10: "next_10_frames", 100: "next_100_frames"}


def _nudge_box(L: w.Layout, handle: str) -> Gtk.Box:
    box = Gtk.Box(halign=Gtk.Align.START)
    box.add_css_class("linked")
    box.add_css_class("sd-nudge")
    for frames, text in NUDGES:
        button = Gtk.Button(label=text, sensitive=False,
                            tooltip_text=_("Move {handle} by {frames} frame(s)").format(
                                handle=_("start") if handle == "start" else _("end"), frames=frames))
        L.add(f"trim_{handle}_{NUDGE_NAMES[frames]}_button", button)
        box.append(button)
    return box


def _slider_row(L: w.Layout, name: str, title: str, subtitle: str, lower: float, upper: float,
                step: float, value: float) -> Adw.ActionRow:
    scale = L.add(name, w.scale(lower, upper, step, value, width=180, draw_value=True))
    scale.add_mark(value, Gtk.PositionType.BOTTOM, None)
    reset = w.icon_button("edit-undo-symbolic", _("Reset"), callback=lambda: scale.set_value(value))
    row = w.widget_row(title, scale, subtitle)
    row.add_suffix(reset)
    return row


def build() -> w.Layout:
    L = w.Layout()

    # ---------------------------------------------------------------- preview
    picture = L.add("preview_picture", Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, hexpand=True,
                                                   vexpand=True, focusable=True))
    picture.set_size_request(320, 240)
    overlay = Gtk.Overlay(child=picture)
    choose = w.label_button(_("Choose File…"), "document-open-symbolic", css=("pill", "suggested-action"))
    L.add("placeholder_choose_button", choose)
    placeholder = Adw.StatusPage(icon_name="sd-trim-symbolic", title=_("No source loaded"),
                                 description=_("Choose a captured file to preview, trim and correct it."),
                                 child=choose)
    placeholder.add_css_class("compact")
    overlay.add_overlay(L.add("preview_placeholder", placeholder))
    frame = Gtk.AspectFrame(ratio=4 / 3, obey_child=False, child=overlay)
    frame.add_css_class("sd-preview")
    frame.set_overflow(Gtk.Overflow.HIDDEN)

    play = L.add("preview_start_button", w.icon_button("media-playback-start-symbolic", _("Play"), flat=False))
    pause = L.add("preview_pause_button", w.icon_button("media-playback-pause-symbolic", _("Pause"), flat=False))
    stop = L.add("preview_stop_button", w.icon_button("media-playback-stop-symbolic", _("Stop preview"),
                                                      flat=False))
    for button in (play, pause, stop):
        button.add_css_class("circular")
    pause.set_sensitive(False)
    stop.set_sensitive(False)
    mute = L.add("preview_mute_check", Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic",
                                                        tooltip_text=_("Mute"), valign=Gtk.Align.CENTER))
    mute.add_css_class("flat")
    volume = L.add("preview_volume_scale", w.scale(0.0, 2.0, 0.01, 1.0, width=110))
    volume.set_hexpand(False)
    volume.set_tooltip_text(_("Preview volume"))
    transport = w.hbox(play, pause, stop, Gtk.Box(hexpand=True), mute, volume, spacing=8)
    position = L.add("preview_position_label", w.label("00:00.000", css=("sd-mono", "dimmed")))
    seek = L.add("preview_seek_scale", w.scale(0.0, 1.0, 0.01, 0.0, width=160))
    seek.set_sensitive(False)
    duration = L.add("preview_duration_label", w.label("00:00.000", css=("sd-mono", "dimmed")))
    seek_row = w.hbox(position, seek, duration, spacing=10)
    preview_status = L.add("preview_status_label", w.label("", css=("sd-meta",), wrap=True))

    # ------------------------------------------------------------------- trim
    summary = L.add("trim_summary_label", w.label(_("Load a file to set clip start and end."), css=("sd-meta",)))
    range_box = L.add("trim_range_placeholder", Gtk.Box(hexpand=True))
    start_label = L.add("trim_start_label", w.label("00:00.000", css=("title-4", "sd-mono")))
    end_label = L.add("trim_end_label", w.label("00:00.000", css=("title-4", "sd-mono")))
    set_start = L.add("trim_set_start_button", w.label_button(_("Set In"), "go-first-symbolic",
                                                              css=("pill", "flat"),
                                                              tooltip=_("Set start from playhead")))
    set_end = L.add("trim_set_end_button", w.label_button(_("Set Out"), "go-last-symbolic",
                                                          css=("pill", "flat"),
                                                          tooltip=_("Set end from playhead")))
    set_start.set_sensitive(False)
    set_end.set_sensitive(False)
    ends = Gtk.Grid(column_spacing=14, row_spacing=6)
    ends.attach(w.caption(_("In")), 0, 0, 1, 1)
    ends.attach(start_label, 0, 1, 1, 1)
    ends.attach(set_start, 1, 1, 1, 1)
    ends.attach(_nudge_box(L, "start"), 0, 2, 2, 1)
    ends.attach(w.caption(_("Out")), 0, 3, 1, 1)
    ends.attach(end_label, 0, 4, 1, 1)
    ends.attach(set_end, 1, 4, 1, 1)
    ends.attach(_nudge_box(L, "end"), 0, 5, 2, 1)
    hint = w.label(_("Seek with the player, then set In/Out from the playhead. Nudge buttons move by frames; "
                     "the arrow keys nudge the selected handle."), css=("sd-meta",), wrap=True)
    trim_card = w.card(w.caption(_("Trim")), range_box, summary, ends, hint, spacing=12)

    info = L.add("info_label", w.label(_("Load a captured file to preview and export corrections."),
                                       css=("sd-meta",), wrap=True))
    preview_col = w.vbox(frame, transport, seek_row, preview_status, trim_card, info, spacing=12)

    # --------------------------------------------------------------- settings
    source = w.group(_("Source"))
    src = L.add("source_entry", PathRow(_("Input media file"), tooltip=_("Choose source")))
    L.add("source_pick_button", src.button)
    source.add(src)
    media = w.action_row(_("Media"), _("No source loaded."))
    media.set_subtitle_selectable(True)
    L.add("source_meta_label", RowSubtitle(media))
    source.add(media)

    export = w.group(_("Export"))
    out = L.add("output_entry", PathRow(_("Output file"), tooltip=_("Choose output file")))
    L.add("out_pick_button", out.button)
    export.add(out)
    export.add(L.add("output_mode_combo", ChoiceRow(_("Mode"), _("Stream copy is lossless and fast"))))
    export.add(L.add("container_combo", ChoiceRow(_("Container"))))

    encode = w.group(_("Re-encode"), _("Used when the mode re-encodes"))
    encode.add(L.add("video_codec_combo", ChoiceRow(_("Video codec"))))
    encode.add(L.add("video_bitrate_entry", EntryRow(_("Video bitrate"), "6M", placeholder="6M")))
    encode.add(L.add("audio_codec_combo", ChoiceRow(_("Audio codec"))))
    encode.add(L.add("audio_bitrate_entry", EntryRow(_("Audio bitrate"), "192k", placeholder="192k")))
    encode.add(L.add("sample_rate_spin", SpinRow(_("Sample rate"), 8000, 192000, 1000, 48000, subtitle="Hz")))
    encode.add(L.add("channels_combo", ChoiceRow(_("Channels"))))
    encode.add(L.add("pix_fmt_combo", ChoiceRow(_("Pixel format"))))
    encode.add(L.add("match_fps_check", SwitchRow(_("Match source frame rate"), active=True)))
    fps = L.add("output_fps_spin", SpinRow(_("Output frame rate"), 1, 120, 0.01, 25.0, digits=3, page=1.0))
    fps.set_sensitive(False)
    encode.add(fps)

    corrections = w.group(_("Corrections"), _("Applied when re-encoding; the preview follows them"))
    corrections.add(L.add("audio_delay_spin", SpinRow(
        _("Audio delay"), -2000, 2000, 10, 0, page=100,
        subtitle=_("ms · positive delays audio, negative advances it"))))
    corrections.add(L.add("deinterlace_check", SwitchRow(_("Deinterlace"),
                                                         _("Removes combing from interlaced VHS fields"))))
    denoise = L.add("denoise_check", SwitchRow(_("Denoise"), _("hqdn3d temporal-spatial cleanup")))
    corrections.add(denoise)
    corrections.add(L.add("denoise_strength_spin", SpinRow(_("Denoise strength"), 0.5, 3.0, 0.1, 1.0, digits=1,
                                                           subtitle=_("Higher removes more noise but blurs"))))
    corrections.add(_slider_row(L, "brightness_scale", _("Brightness"), _("Keep low to avoid clipping"),
                                -0.2, 0.2, 0.01, 0.0))
    corrections.add(_slider_row(L, "contrast_scale", _("Contrast"), _("Separation of darks and brights"),
                                0.5, 2.0, 0.01, 1.0))
    corrections.add(_slider_row(L, "saturation_scale", _("Saturation"), _("Lower reduces colour noise"),
                                0.0, 2.0, 0.01, 1.0))
    corrections.add(L.add("audio_gain_spin", SpinRow(_("Audio gain"), -24.0, 24.0, 0.5, 0.0, digits=1,
                                                     subtitle="dB")))
    corrections.add(L.add("highpass_spin", SpinRow(_("High-pass"), 0, 500, 5, 0, page=25,
                                                   subtitle=_("Hz · removes rumble · 0 = off"))))
    corrections.add(L.add("lowpass_spin", SpinRow(_("Low-pass"), 0, 20000, 100, 0, page=500,
                                                  subtitle=_("Hz · removes hiss · 0 = off"))))

    settings_col = w.vbox(source, export, encode, corrections, spacing=22)

    status = L.add("status_label", w.notice("sd-notice"))
    command, buffer, _view = w.code_view("", "sh", title=_("Export command"), min_height=60)
    L.add("command_buffer", buffer)
    content = w.vbox(status, w.columns(preview_col, settings_col, spacing=24), command, spacing=22)

    log_scroller, log_view = w.log_view()
    L.add("log_view", log_view)
    L.add("log_dialog", w.TextDialog(_("Export log"), log_scroller))

    dock_status = L.add("dock_status", w.dock_status())
    log_button = L.add("log_button", w.label_button(_("Log"), "utilities-terminal-symbolic", css=("pill", "flat")))
    stop_export = L.add("stop_button", w.label_button(_("Stop"), "media-playback-stop-symbolic",
                                                      css=("pill", "flat")))
    stop_export.set_sensitive(False)
    start_export = L.add("start_button", w.label_button(_("Export"), "document-save-symbolic",
                                                        css=("pill", "suggested-action", "sd-primary")))
    L.add("edit_page_root", w.page_view(content, w.dock(dock_status, log_button, stop_export, start_export),
                                        max_width=1400))
    return L
