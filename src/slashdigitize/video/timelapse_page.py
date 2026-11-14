"""Timelapse workflow: images to video with FFmpeg (moved out of the main window)."""
from __future__ import annotations

import os
import shlex
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.ui.rows import ChoiceRow, EntryRow, PathRow, SpinRow, SwitchRow  # noqa: E402
from slashdigitize.video.encode import (  # noqa: E402
    SUPPORTED_IMAGE_EXTENSIONS,
    build_command_preview,
    build_ffmpeg_command,
    collect_inputs,
    prepare_inputs_for_timelapse,
    quality_flag_for_codec,
    write_concat_file,
)
from slashdigitize.video.ffmpeg import detect_ffmpeg  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402
from slashdigitize.video.runner import FFmpegRunner  # noqa: E402

PRESETS_X264 = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower",
                "veryslow", "placebo"]
PRESETS_NVENC = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "fast", "medium", "slow"]


class RowSubtitle:
    """Label-like ``set_text``/``get_text`` that writes a row subtitle."""

    def __init__(self, row: Adw.ActionRow):
        self.row = row

    def set_text(self, text: str) -> None:
        self.row.set_subtitle(text or "")

    def get_text(self) -> str:
        return self.row.get_subtitle() or ""


class TimelapsePage(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.input_items: list[str] = []
        self.output_auto = True
        self._setting_output = False
        self._concat_list_path: str | None = None
        self._prepared_input_tempdir: str | None = None
        self.last_folder_path: str | None = None
        self._encoders = []
        self._pixel_formats = []
        self._encoder_details: dict[str, str] = {}
        self._hardware_info = None
        self._ffmpeg_command: list[str] | None = None
        self.runner = FFmpegRunner(self._on_runner_output, self._on_runner_exit)
        self._build_ui()
        self._refresh_input_list()
        self.update_preview()

    # ---------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        # Inputs
        self.path_entry = EntryRow(_("Add a path"), placeholder=_("image file or folder"))
        self.path_entry.set_show_apply_button(True)
        self.path_entry.connect("apply", self.on_add_path_clicked)
        self.path_entry.connect("entry-activated", self.on_add_path_clicked)
        self.path_entry.set_tooltip_text(_("Paste an image file path or a folder path."))
        add_files = w.label_button(_("Add Files…"), "list-add-symbolic", css=("flat",),
                                   tooltip=_("Pick one or more image files."))
        add_files.connect("clicked", self.on_add_files_clicked)
        add_folder = w.label_button(_("Add Folder…"), "folder-open-symbolic", css=("flat",),
                                    tooltip=_("Pick a folder and load supported images inside it."))
        add_folder.connect("clicked", self.on_add_folder_clicked)
        clear = w.icon_button("edit-clear-all-symbolic", _("Clear all inputs."))
        clear.connect("clicked", self.on_clear_inputs_clicked)
        self.inputs_group = w.group(_("Inputs"), suffix=w.hbox(add_files, add_folder, clear, spacing=2))
        self.input_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.input_list.add_css_class("boxed-list")
        placeholder = Adw.StatusPage(icon_name="sd-timelapse-symbolic", title=_("Drop images or folders"),
                                     description=_("JPEG, PNG, TIFF and camera RAW (embedded preview)."))
        placeholder.add_css_class("compact")
        self.input_list.set_placeholder(placeholder)
        self.inputs_group.add(self.input_list)
        path_group = w.group()
        path_group.add(self.path_entry)
        inputs = w.vbox(self.inputs_group, path_group, spacing=10)
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_drop)
        drop_target.connect("enter", lambda *_: (inputs.add_css_class("sd-drop-hover"), Gdk.DragAction.COPY)[1])
        drop_target.connect("leave", lambda *_: inputs.remove_css_class("sd-drop-hover"))
        inputs.add_controller(drop_target)

        # Output
        output = w.group(_("Output"), _("Default is the same folder as your images."))
        self.output_entry = PathRow(_("Save as"), tooltip=_("Choose the output file path."))
        self.output_entry.connect("changed", self.on_output_changed)
        self.output_entry.button.connect("clicked", self.on_choose_output_clicked)
        output.add(self.output_entry)
        self.output_size_combo = ChoiceRow(_("Resolution"))
        for key, title in [("1080", "Fit within 1920 × 1080"), ("2160", "Fit within 3840 × 2160"),
                           ("source", "Source dimensions (advanced)")]:
            self.output_size_combo.append(key, title)
        self.output_size_combo.set_active_id("1080")
        self.output_size_combo.set_subtitle(_("Bounded for compatible playback"))
        self.output_size_combo.set_tooltip_text(
            "Bound output size for compatible playback; source-sized frames may require substantial memory.")
        self.output_size_combo.connect("changed", self.on_settings_changed)
        output.add(self.output_size_combo)
        self.fps_spin = SpinRow(_("Frame rate"), 1, 240, 1, 25, subtitle=_("Frames per second of the video"))
        self.fps_spin.connect("value-changed", self.on_settings_changed)
        output.add(self.fps_spin)

        # Encoding
        enc = w.group(_("Encoding"))
        self.codec_combo = ChoiceRow(_("Video codec"))
        self.codec_combo.connect("changed", self.on_codec_changed)
        enc.add(self.codec_combo)
        self.codec_info_label = RowSubtitle(self.codec_combo)
        self.show_all_check = SwitchRow(_("Show codecs without hardware"),
                                        _("Include encoders whose GPU was not found"))
        self.show_all_check.connect("toggled", self.on_show_all_toggled)
        enc.add(self.show_all_check)
        self.quality_check = SwitchRow(_("Constant quality"),
                                       _("-crf for x264/x265/AV1/VP9, -cq for NVENC"), active=True)
        self.quality_check.connect("toggled", self.on_quality_toggled)
        enc.add(self.quality_check)
        self.quality_spin = SpinRow(_("Quality"), 0, 51, 1, 18, subtitle=_("Lower is better · 18 ≈ visually lossless"))
        self.quality_spin.connect("value-changed", self.on_settings_changed)
        enc.add(self.quality_spin)
        self.preset_combo = ChoiceRow(_("Preset"))
        self.preset_combo.connect("changed", self.on_settings_changed)
        enc.add(self.preset_combo)
        advanced = Adw.ExpanderRow(title=_("Advanced"), subtitle=_("Pixel format, tune, extra arguments"))
        advanced.add_prefix(Gtk.Image.new_from_icon_name("preferences-other-symbolic"))
        self.pix_combo = ChoiceRow(_("Pixel format"))
        self.pix_combo.connect("changed", self.on_settings_changed)
        advanced.add_row(self.pix_combo)
        self.tune_entry = EntryRow(_("Tune"), placeholder=_("e.g. film, grain"))
        self.tune_entry.connect("changed", self.on_settings_changed)
        advanced.add_row(self.tune_entry)
        self.extra_entry = EntryRow(_("Extra FFmpeg arguments"), placeholder=_("appended at the end"))
        self.extra_entry.connect("changed", self.on_settings_changed)
        advanced.add_row(self.extra_entry)
        enc.add(advanced)

        code, self.command_buffer, self.command_view = w.code_view("", "sh", title=_("Command preview"),
                                                                  min_height=90)
        self.encode_status = w.notice("sd-notice")

        log_scroller, self.log_view = w.log_view()
        self.log_buffer = self.log_view.get_buffer()
        self.log_dialog = w.TextDialog(_("Timelapse log"), log_scroller)

        content = w.vbox(w.columns(inputs, w.vbox(output, enc, spacing=22), spacing=24),
                         self.encode_status, code, spacing=22)

        self.dock_status = w.dock_status()
        log_button = w.label_button(_("Log"), "utilities-terminal-symbolic", css=("pill", "flat"))
        log_button.connect("clicked", lambda *_: self.log_dialog.present(self))
        self.stop_button = w.label_button(_("Stop"), "media-playback-stop-symbolic", css=("pill", "flat"),
                                          tooltip=_("Stop the running FFmpeg process."))
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop_clicked)
        self.start_button = w.label_button(_("Render"), "media-playback-start-symbolic",
                                           css=("pill", "suggested-action", "sd-primary"),
                                           tooltip=_("Start rendering with FFmpeg."))
        self.start_button.connect("clicked", self.on_start_clicked)
        self.append(w.page_view(content, w.dock(self.dock_status, log_button, self.stop_button,
                                                self.start_button)))

    # ------------------------------------------------------------ app hooks
    def sync_capabilities(self, ffmpeg_command=None, encoders=None, pixel_formats=None, hardware_info=None, **_):
        self._ffmpeg_command = ffmpeg_command
        self._encoders = encoders or []
        self._pixel_formats = pixel_formats or []
        self._hardware_info = hardware_info
        self._populate_codec_combo()
        self._populate_pix_fmt_combo()
        self._populate_preset_combo(self.codec_combo.get_active_id())
        self._update_codec_info()
        self.update_preview()

    @property
    def running(self) -> bool:
        return self.runner.running

    def shutdown(self) -> None:
        self._cleanup_concat_file()
        self._cleanup_prepared_inputs()

    def _update_dock(self) -> None:
        if self.runner.running:
            self.dock_status.set_text(_("Rendering…"))
            return
        count = len(self.input_items)
        self.start_button.set_sensitive(bool(count))
        if not count:
            self.dock_status.set_text(_("Add images to start"))
        else:
            out = os.path.basename(self.output_entry.get_text().strip()) or "—"
            self.dock_status.set_text(f"{count} " + (_("input") if count == 1 else _("inputs")) + f" → {out}")

    def _populate_codec_combo(self) -> None:
        selected = self.codec_combo.get_active_id()
        self.codec_combo.remove_all()

        self.codec_combo.append("auto", _("Auto"))

        encoders = [enc for enc in self._encoders if enc.kind == "video"]
        show_unusable = self.show_all_check.get_active()
        if not show_unusable:
            encoders = [enc for enc in encoders if self._encoder_is_usable(enc.name)]

        encoder_by_name = {}
        for encoder in encoders:
            if encoder.name not in encoder_by_name:
                encoder_by_name[encoder.name] = encoder

        self._encoder_details = {name: enc.description for name, enc in encoder_by_name.items()}

        names = sorted(encoder_by_name.keys(), key=str.casefold)
        for name in names:
            description = self._encoder_details.get(name, "")
            label = name
            if show_unusable and not self._encoder_is_usable(name):
                label = f"{name} ({_('HW missing')})"
            if description:
                label = f"{label} - {description}"
            self.codec_combo.append(name, label)

        if selected and selected in names:
            self.codec_combo.set_active_id(selected)
            return

        if "libx264" in names:
            self.codec_combo.set_active_id("libx264")
        elif names:
            self.codec_combo.set_active_id(names[0])
        else:
            self.codec_combo.set_active_id("auto")

    def _populate_preset_combo(self, codec: str | None) -> None:
        selected = self.preset_combo.get_active_id()
        self.preset_combo.remove_all()

        self.preset_combo.append("auto", _("Auto"))

        preset_list = PRESETS_X264
        if codec and codec not in ("auto", ""):
            if "nvenc" in codec.lower():
                preset_list = PRESETS_NVENC

        for preset in preset_list:
            self.preset_combo.append(preset, preset)

        if codec in (None, "auto", ""):
            self.preset_combo.set_active_id("auto")
            return

        if selected and selected in preset_list:
            self.preset_combo.set_active_id(selected)
        elif "p4" in preset_list:
            self.preset_combo.set_active_id("p4")
        elif "medium" in preset_list:
            self.preset_combo.set_active_id("medium")
        else:
            self.preset_combo.set_active_id("auto")
        self._update_preset_tooltip()

    def _update_codec_info(self) -> None:
        codec_id = self.codec_combo.get_active_id()
        if not codec_id or codec_id == "auto":
            self.codec_info_label.set_text(_("Auto uses the FFmpeg default encoder."))
            return
        description = self._encoder_details.get(codec_id, "")
        if description:
            self.codec_info_label.set_text(f"{codec_id} - {description}")
        else:
            self.codec_info_label.set_text(codec_id)
        self.codec_combo.set_tooltip_text(self.codec_info_label.get_text())

    def _encoder_is_usable(self, name: str) -> bool:
        if self._hardware_info is None or not getattr(self._hardware_info, "known", False):
            return True
        requirement = self._encoder_requirement(name)
        if requirement is None:
            return True
        vendors = getattr(self._hardware_info, "vendors", set())
        if "any" in requirement:
            return bool(vendors)
        return bool(vendors.intersection(requirement))

    def _encoder_requirement(self, name: str) -> set[str] | None:
        lower = name.lower()
        if "_nvenc" in lower:
            return {"nvidia"}
        if "_qsv" in lower:
            return {"intel"}
        if "_amf" in lower:
            return {"amd"}
        if "_vaapi" in lower:
            return {"intel", "amd"}
        if "_vdpau" in lower:
            return {"nvidia", "amd"}
        if "_vulkan" in lower:
            return {"any"}
        if "_opencl" in lower:
            return {"any"}
        return None

    def _populate_pix_fmt_combo(self) -> None:
        selected = self.pix_combo.get_active_id()
        self.pix_combo.remove_all()

        self.pix_combo.append("auto", _("Auto"))

        names = sorted({fmt.name for fmt in self._pixel_formats}, key=str.casefold)
        for name in names:
            self.pix_combo.append(name, name)

        if selected and selected in names:
            self.pix_combo.set_active_id(selected)
            return

        if "yuv420p" in names:
            self.pix_combo.set_active_id("yuv420p")
        elif names:
            self.pix_combo.set_active_id(names[0])
        else:
            self.pix_combo.set_active_id("auto")
        self._update_pix_fmt_tooltip()

    def _update_pix_fmt_tooltip(self) -> None:
        pix_id = self.pix_combo.get_active_id()
        if not pix_id or pix_id == "auto":
            self.pix_combo.set_tooltip_text(_("Pixel format. Auto lets FFmpeg choose."))
        else:
            self.pix_combo.set_tooltip_text(_("Pixel format: ") + pix_id)

    def _update_preset_tooltip(self) -> None:
        preset_id = self.preset_combo.get_active_id()
        if not preset_id or preset_id == "auto":
            self.preset_combo.set_tooltip_text(_("Preset. Auto skips -preset."))
        else:
            self.preset_combo.set_tooltip_text(_("Preset: ") + preset_id)

    def on_add_path_clicked(self, _button: Gtk.Button | Gtk.Entry) -> None:
        path = self.path_entry.get_text().strip()
        if path:
            self.add_paths([path])
        self.path_entry.set_text("")

    def on_add_files_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select images"))
        dialog.set_modal(True)
        if self.last_folder_path:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_folder_path))

        filters = Gio.ListStore.new(Gtk.FileFilter)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(_("Supported images"))
        for ext in sorted(SUPPORTED_IMAGE_EXTENSIONS):
            image_filter.add_suffix(ext[1:])
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(image_filter)

        dialog.open_multiple(self.get_root(), None, self._on_files_selected)

    def _on_files_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return

        paths = self._extract_paths(files)
        self._remember_last_folder(paths)
        self.add_paths(paths)

    def on_add_folder_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select folder"))
        dialog.set_modal(True)
        if self.last_folder_path:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_folder_path))
        dialog.select_folder(self.get_root(), None, self._on_folder_selected)

    def _on_folder_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is None:
            return
        path = folder.get_path()
        if path:
            self._remember_last_folder([path])
            self.add_paths([path])

    def on_clear_inputs_clicked(self, _button: Gtk.Button) -> None:
        self.input_items = []
        self._refresh_input_list()
        self.update_preview()

    def on_drop(self, _target: Gtk.DropTarget, value, _x: float, _y: float) -> bool:
        paths: list[str] = []
        if hasattr(value, "get_files"):
            paths = self._extract_paths(value.get_files())
        if paths:
            self.add_paths(paths)
            return True
        return False

    def _extract_paths(self, files) -> list[str]:
        paths: list[str] = []
        if files is None:
            return paths
        if hasattr(files, "get_n_items"):
            for index in range(files.get_n_items()):
                file = files.get_item(index)
                if file is None:
                    continue
                path = file.get_path()
                if path:
                    paths.append(path)
            return paths
        try:
            for file in files:
                path = file.get_path()
                if path:
                    paths.append(path)
        except TypeError:
            return []
        return paths

    def _remember_last_folder(self, paths: list[str]) -> None:
        for path in paths:
            if not path:
                continue
            if os.path.isdir(path):
                self.last_folder_path = path
                return
            if os.path.isfile(path):
                self.last_folder_path = os.path.dirname(path)
                return

    def add_paths(self, paths: list[str]) -> None:
        changed = False
        for path in paths:
            if path and path not in self.input_items:
                self.input_items.append(path)
                changed = True

        if changed:
            self._remember_last_folder(paths)
            self._refresh_input_list()
            self._update_default_output()
            self.update_preview()

    def _refresh_input_list(self) -> None:
        child = self.input_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            if isinstance(child, Gtk.ListBoxRow):
                self.input_list.remove(child)
            child = next_child

        for path in self.input_items:
            folder = os.path.isdir(path)
            row = w.action_row(os.path.basename(path.rstrip(os.sep)) or path,
                               (_("Folder: ") if folder else "") + path)
            row.set_subtitle_lines(1)
            row.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic" if folder else "image-x-generic-symbolic"))
            remove_button = w.icon_button("list-remove-symbolic", _("Remove this input from the list."))
            remove_button.connect("clicked", self.on_remove_input_clicked, path)
            row.add_suffix(remove_button)
            self.input_list.append(row)

        if self.input_items:
            self.inputs_group.set_description(_("Inputs: ") + str(len(self.input_items)))
        else:
            self.inputs_group.set_description(_("Drag and drop files or folders here."))
        self._update_dock()

    def on_remove_input_clicked(self, _button: Gtk.Button, path: str) -> None:
        if path in self.input_items:
            self.input_items.remove(path)
            self._refresh_input_list()
            self._update_default_output()
            self.update_preview()

    def _update_default_output(self) -> None:
        if not self.output_auto:
            return
        if not self.input_items:
            return
        first = self.input_items[0]
        if os.path.isdir(first):
            base_dir = first
        else:
            base_dir = os.path.dirname(first)
        output_path = os.path.join(base_dir, "output.mp4")
        self._set_output_path(output_path, auto=True)

    def _set_output_path(self, path: str, auto: bool) -> None:
        self._setting_output = True
        self.output_entry.set_text(path)
        self._setting_output = False
        self.output_auto = auto

    def on_output_changed(self, _entry: Gtk.Entry) -> None:
        if not self._setting_output:
            self.output_auto = False
        self.update_preview()

    def on_choose_output_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Select output file"))
        dialog.set_modal(True)
        if self.last_folder_path:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_folder_path))
        dialog.save(self.get_root(), None, self._on_output_selected)

    def _on_output_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            self._remember_last_folder([path])
            self._set_output_path(path, auto=False)
            self.update_preview()

    def on_codec_changed(self, _widget) -> None:
        codec_id = self.codec_combo.get_active_id()
        self._populate_preset_combo(codec_id)
        self._update_codec_info()
        self.update_preview()

    def on_show_all_toggled(self, _button: Gtk.CheckButton) -> None:
        self._populate_codec_combo()
        self.on_codec_changed(self.codec_combo)

    def on_quality_toggled(self, _button: Gtk.CheckButton) -> None:
        self.quality_spin.set_sensitive(self.quality_check.get_active())
        self.update_preview()

    def on_settings_changed(self, _widget) -> None:
        self._update_preset_tooltip()
        self._update_pix_fmt_tooltip()
        self.update_preview()

    def _selected_preset(self) -> str | None:
        preset_id = self.preset_combo.get_active_id()
        if preset_id in (None, "auto"):
            return None
        return preset_id

    def _output_size(self):
        key = self.output_size_combo.get_active_id()
        return {"1080": (1920, 1080), "2160": (3840, 2160)}.get(key)

    def update_preview(self) -> None:
        self.encode_status.set_text("")
        self._update_dock()

        if not self._ffmpeg_command:
            self.command_buffer.set_text(_("FFmpeg not found."))
            return

        output_path = self.output_entry.get_text().strip()
        if not output_path:
            self.command_buffer.set_text(_("Choose an output file to see the command."))
            return

        collection = collect_inputs(self.input_items)
        warnings: list[str] = []
        if collection.warnings:
            warnings.extend(collection.warnings)
        if not collection.paths:
            self.command_buffer.set_text(_("Add images or folders to build the command."))
            return

        codec_id = self.codec_combo.get_active_id()
        codec = None if codec_id in (None, "auto") else codec_id

        quality = int(self.quality_spin.get_value()) if self.quality_check.get_active() else None
        preset = self._selected_preset()
        tune = self.tune_entry.get_text().strip() or None

        quality_flag = quality_flag_for_codec(codec) if quality is not None else None
        if quality is not None and codec is not None and quality_flag is None:
            warnings.append(_("Quality setting is ignored for this codec."))

        pix_id = self.pix_combo.get_active_id()
        pix_fmt = None if pix_id in (None, "auto") else pix_id
        if pix_fmt is None and codec and "nvenc" in codec.lower():
            pix_fmt = "yuv420p"
            warnings.append(_("Pixel format set to yuv420p for NVENC."))

        if self._output_size() is None:
            warnings.append("Source dimensions selected: huge frames may exceed decoder or GPU memory limits.")
        fps = self.fps_spin.get_value()
        extra_args = self.extra_entry.get_text().strip() or None

        preview = build_command_preview(
            ffmpeg_cmd=self._ffmpeg_command,
            output_file=output_path,
            fps=fps,
            codec=codec,
            quality=quality,
            preset=preset,
            tune=tune,
            pix_fmt=pix_fmt,
            extra_args=extra_args,
            output_size=self._output_size(),
        )
        self.command_buffer.set_text(preview)
        if warnings:
            self.encode_status.set_text("\n".join(warnings))

    def on_start_clicked(self, _button: Gtk.Button) -> None:
        if self.runner.running:
            return

        info = detect_ffmpeg()
        if not info.command:
            self.encode_status.set_text(_("FFmpeg not found. Install it or ensure it is in PATH."))
            return

        output_path = self.output_entry.get_text().strip()
        if not output_path:
            self.encode_status.set_text(_("Please choose an output file."))
            return
        output_path = os.path.abspath(os.path.expanduser(output_path))
        output_dir = os.path.dirname(output_path)

        collection = collect_inputs(self.input_items)
        warnings: list[str] = []
        if collection.warnings:
            warnings.extend(collection.warnings)
        if not collection.paths:
            self.encode_status.set_text(_("No supported images found."))
            return

        codec_id = self.codec_combo.get_active_id()
        codec = None if codec_id in (None, "auto") else codec_id

        quality = int(self.quality_spin.get_value()) if self.quality_check.get_active() else None
        preset = self._selected_preset()
        tune = self.tune_entry.get_text().strip() or None

        pix_id = self.pix_combo.get_active_id()
        pix_fmt = None if pix_id in (None, "auto") else pix_id
        if pix_fmt is None and codec and "nvenc" in codec.lower():
            pix_fmt = "yuv420p"
            warnings.append(_("Pixel format set to yuv420p for NVENC."))

        if self._output_size() is None:
            warnings.append("Source dimensions selected: huge frames may exceed decoder or GPU memory limits.")
        fps = self.fps_spin.get_value()
        extra_args = self.extra_entry.get_text().strip() or None

        self._cleanup_concat_file()
        self._cleanup_prepared_inputs()
        try:
            prepared = prepare_inputs_for_timelapse(collection.paths, temp_parent=output_dir)
            self._prepared_input_tempdir = prepared.temp_dir
            list_file = write_concat_file(prepared.paths, fps, directory=output_dir)
        except Exception as exc:
            self._cleanup_prepared_inputs()
            self.encode_status.set_text(str(exc))
            return

        if prepared.warnings:
            warnings.extend(prepared.warnings)
        self._concat_list_path = list_file

        cmd = build_ffmpeg_command(
            ffmpeg_cmd=info.command,
            list_file=list_file,
            output_file=output_path,
            fps=fps,
            codec=codec,
            quality=quality,
            preset=preset,
            tune=tune,
            pix_fmt=pix_fmt,
            extra_args=extra_args,
            output_size=self._output_size(),
        )

        if quality is not None and codec is not None and quality_flag_for_codec(codec) is None:
            warnings.append(_("Quality setting is ignored for this codec."))

        if warnings:
            self.encode_status.set_text("\n".join(warnings))

        self._clear_log()
        if self._prepared_input_tempdir:
            self._append_log(_("RAW preview fallback active. Using embedded JPEG previews for timelapse input."))
        self._append_log(_("Running:") + " " + shlex.join(cmd))

        try:
            self.runner.start(cmd)
        except Exception as exc:
            self._cleanup_concat_file()
            self._cleanup_prepared_inputs()
            self.encode_status.set_text(str(exc))
            return

        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self._update_dock()

    def on_stop_clicked(self, _button: Gtk.Button) -> None:
        self.runner.stop()

    def _on_runner_output(self, line: str) -> None:
        GLib.idle_add(self._append_log, line)

    def _on_runner_exit(self, rc: int) -> None:
        GLib.idle_add(self._handle_runner_exit, rc)

    def _handle_runner_exit(self, rc: int) -> None:
        self.start_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.encode_status.set_text(_("FFmpeg finished with code ") + str(rc))
        self._update_dock()
        w.toast(self, _("Timelapse rendered") if rc == 0 else _("FFmpeg finished with code ") + str(rc))
        self._cleanup_concat_file()
        self._cleanup_prepared_inputs()

    def _cleanup_concat_file(self) -> None:
        if self._concat_list_path and os.path.exists(self._concat_list_path):
            try:
                os.remove(self._concat_list_path)
            except OSError:
                pass
        self._concat_list_path = None

    def _cleanup_prepared_inputs(self) -> None:
        if self._prepared_input_tempdir and os.path.isdir(self._prepared_input_tempdir):
            shutil.rmtree(self._prepared_input_tempdir, ignore_errors=True)
        self._prepared_input_tempdir = None

    def _clear_log(self) -> None:
        self.log_buffer.set_text("")

    def _append_log(self, line: str) -> bool:
        start_iter = self.log_buffer.get_start_iter()
        self.log_buffer.insert(start_iter, line + "\n")
        return False
