"""Layout of the VapourSynth processing page (replaces vapoursynth_process_page.ui).

Widget names match the former GtkBuilder ids, so VapourSynthProcessPage logic
binds to them unchanged through ``Layout.get_object``."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.ui.rows import ChoiceRow, EntryRow, PathRow, SpinRow, SwitchRow  # noqa: E402
from slashdigitize.video.capture_layout import RowSubtitle  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402


def build() -> w.Layout:
    L = w.Layout()

    status = L.add("vs_status_label", w.label(_("Checking VapourSynth…"), css=("sd-meta",), wrap=True))
    status_icon = Gtk.Image.new_from_icon_name("sd-vapoursynth-symbolic")
    status_icon.set_pixel_size(28)
    status_icon.add_css_class("accent")
    status.set_hexpand(True)
    hero = w.card(w.hbox(status_icon, status, spacing=14), css="sd-hero")

    # ----------------------------------------------------------------- source
    source = w.group(_("Source"))
    src = L.add("source_entry", PathRow(_("Input media file"), tooltip=_("Choose source")))
    L.add("source_pick_button", src.button)
    source.add(src)
    media = w.action_row(_("Media"), _("No source loaded."))
    media.set_subtitle_selectable(True)
    L.add("source_meta_label", RowSubtitle(media))
    spinner = L.add("source_probe_spinner", Gtk.Spinner(valign=Gtk.Align.CENTER))
    media.add_suffix(spinner)
    probe = L.add("source_probe_box", Gtk.Box(spacing=8, visible=False))
    probe.append(L.add("source_probe_label", w.label(_("Importing source metadata..."), css=("sd-meta",))))
    media.add_suffix(probe)
    source.add(media)

    # --------------------------------------------------------------- pipeline
    pipeline = w.group(_("Pipeline"), _("Choose a processing profile or tune it below"))
    preset = L.add("pipeline_preset_combo", ChoiceRow(_("Preset")))
    apply_button = L.add("pipeline_apply_button", w.label_button(_("Apply"), None, css=("flat",)))
    preset.add_suffix(apply_button)
    L.add("pipeline_preset_desc_label", RowSubtitle(preset))
    pipeline.add(preset)
    pipeline.add(L.add("deinterlace_combo", ChoiceRow(_("Deinterlace"))))
    pipeline.add(L.add("field_order_combo", ChoiceRow(_("Field order"))))
    pipeline.add(L.add("cleanup_combo", ChoiceRow(_("VHS cleanup"))))

    qtgmc = L.add("qtgmc_advanced_frame", w.group(_("QTGMC advanced"), _("“auto” leaves the preset default")))
    expander = Adw.ExpanderRow(title=_("QTGMC parameters"),
                               subtitle=_("SourceMatch, MatchPreset, TR0–TR2, denoise, extra arguments"))
    expander.add_prefix(Gtk.Image.new_from_icon_name("preferences-other-symbolic"))
    for name, title in [("source_match_combo", "SourceMatch"), ("match_preset_combo", "MatchPreset"),
                        ("match_preset2_combo", "MatchPreset2"), ("match_tr2_combo", "MatchTR2"),
                        ("lossless_combo", "Lossless"), ("tr0_combo", "TR0"), ("tr1_combo", "TR1"),
                        ("tr2_combo", "TR2"), ("input_type_combo", "InputType"),
                        ("qtgmc_tuning_combo", _("Tuning"))]:
        expander.add_row(L.add(name, ChoiceRow(title)))
    expander.add_row(L.add("sharpness_entry", EntryRow("Sharpness", placeholder="auto")))
    expander.add_row(L.add("ez_denoise_entry", EntryRow("EZDenoise", placeholder="auto/off")))
    expander.add_row(L.add("ez_keep_grain_entry", EntryRow("EZKeepGrain", placeholder="auto/off")))
    expander.add_row(L.add("fps_divisor_spin", SpinRow("FPSDivisor", 1, 8, 1, 1)))
    expander.add_row(L.add("qtgmc_show_settings_check", SwitchRow(_("ShowSettings in log"))))
    expander.add_row(L.add("qtgmc_extra_args_entry", EntryRow(_("Extra QTGMC arguments"),
                                                              placeholder='NoiseProcess=1, Denoiser="dfttest"')))
    qtgmc.add(expander)

    script_group = w.group(_("Script"))
    script_group.add(L.add("use_custom_script_check", SwitchRow(
        _("Edit script by hand"), _("Replaces the preset generator with your own script"))))
    script_card, _buffer, script_view = w.code_view("", "python3", title=_("VapourSynth script"),
                                                    editable=True, min_height=220, max_height=520,
                                                    line_numbers=True, wrap=False)
    L.add("custom_script_view", script_view)
    note = L.add("script_note_label", w.label("", css=("sd-meta",), wrap=True))

    left = w.vbox(source, pipeline, qtgmc, w.vbox(script_group, script_card, note, spacing=10), spacing=22)

    # ----------------------------------------------------------------- output
    output = w.group(_("Output"))
    out = L.add("output_entry", PathRow(_("Output file"), tooltip=_("Choose output file")))
    L.add("out_pick_button", out.button)
    output.add(out)
    output.add(L.add("output_mode_combo", ChoiceRow(_("Mode"))))
    output.add(L.add("container_combo", ChoiceRow(_("Container"))))

    video = w.group(_("Video"))
    video.add(L.add("video_codec_combo", ChoiceRow(_("Video codec"))))
    video.add(L.add("video_preset_combo", ChoiceRow(_("Preset"))))
    video.add(L.add("video_rate_mode_combo", ChoiceRow(_("Rate control"))))
    video.add(L.add("video_rate_value_entry", EntryRow(_("Rate value"), "6M", placeholder="6M / 18")))
    video.add(L.add("pix_fmt_combo", ChoiceRow(_("Pixel format"))))
    video.add(L.add("match_fps_check", SwitchRow(_("Automatic frame rate"), _("Use the VapourSynth output rate"),
                                                 active=True)))
    fps = L.add("output_fps_spin", SpinRow(_("Output frame rate"), 1, 120, 0.01, 25.0, digits=3, page=1.0))
    fps.set_sensitive(False)
    video.add(fps)

    audio = w.group(_("Audio"))
    audio.add(L.add("audio_codec_combo", ChoiceRow(_("Audio codec"))))
    audio.add(L.add("audio_bitrate_entry", EntryRow(_("Audio bitrate"), "192k", placeholder="192k")))
    audio.add(L.add("sample_rate_spin", SpinRow(_("Sample rate"), 8000, 192000, 1000, 48000, subtitle="Hz")))
    audio.add(L.add("channels_combo", ChoiceRow(_("Channels"))))

    queue = w.group(_("Batch queue"), _("Queue several exports and run them one after another"))
    show_queue = L.add("show_queue_button", Gtk.Button(label=_("Show queue"), valign=Gtk.Align.CENTER))
    show_queue.add_css_class("flat")
    add_queue = L.add("add_queue_button", w.label_button(_("Add"), "list-add-symbolic", css=("flat",),
                                                         tooltip=_("Add the current settings to the queue")))
    run_queue = L.add("run_queue_button", w.label_button(_("Run"), "media-playlist-consecutive-symbolic",
                                                         css=("flat",), tooltip=_("Run all pending queue items")))
    queue_row = w.action_row(_("Queue"), _("Current source, script and output settings"))
    queue_row.add_prefix(Gtk.Image.new_from_icon_name("view-list-symbolic"))
    for button in (add_queue, run_queue, show_queue):
        queue_row.add_suffix(button)
    queue.add(queue_row)

    right = w.vbox(output, video, audio, queue, spacing=22)

    status_label = L.add("status_label", w.notice("sd-notice"))
    command, _cbuf, command_view = w.code_view("", "sh", title=_("Export command"), min_height=60)
    L.add("command_view", command_view)
    content = w.vbox(hero, status_label, w.columns(left, right, spacing=24), command, spacing=22)

    log_scroller, log_view = w.log_view()
    L.add("log_view", log_view)
    L.add("log_dialog", w.TextDialog(_("VapourSynth log"), log_scroller))

    dock_status = L.add("dock_status", w.dock_status())
    log_button = L.add("log_expander", w.label_button(_("Log"), "utilities-terminal-symbolic", css=("pill", "flat")))
    stop = L.add("stop_button", w.label_button(_("Stop"), "media-playback-stop-symbolic", css=("pill", "flat")))
    stop.set_sensitive(False)
    start = L.add("start_button", w.label_button(_("Export"), "document-save-symbolic",
                                                 css=("pill", "suggested-action", "sd-primary")))
    L.add("vapoursynth_process_page_root", w.page_view(
        content, w.dock(dock_status, log_button, stop, start), max_width=1400))
    return L
