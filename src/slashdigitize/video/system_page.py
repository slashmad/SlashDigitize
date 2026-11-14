"""System & codecs: what this machine can capture, decode and encode."""
from __future__ import annotations

import re
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402

HW_SUFFIXES = ("_nvenc", "_qsv", "_amf", "_vaapi", "_vdpau", "_vulkan", "_opencl", "_v4l2m2m", "_cuda", "_mf")
GST_FACTORIES = ["playbin", "gtk4paintablesink", "wavparse", "avdec_h264", "avdec_ffv1"]
COMMON_VIDEO = ["ffv1", "libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9", "prores_ks", "dnxhd",
                "mpeg2video", "mjpeg", "utvideo", "huffyuv", "magicyuv", "rawvideo", "libxvid"]
COMMON_AUDIO = ["flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "aac", "libopus", "libmp3lame", "ac3", "mp2",
                "libvorbis", "alac"]
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PCI_RE = re.compile(r"^([0-9a-fA-F:.]+)\s+(?:VGA compatible controller|3D controller|Display controller):\s*(.*)$")


def _gpu_name(line: str) -> tuple[str, str]:
    """'18:00.0 VGA compatible controller: NVIDIA … [GeForce RTX 3080] (rev a1)' → name, detail."""
    match = PCI_RE.match(line.strip())
    if not match:
        return line.strip(), ""
    address, name = match.groups()
    name = re.sub(r"\s*\(rev [0-9a-f]+\)$", "", name)
    lowered = name.lower()
    vendor = ("NVIDIA" if "nvidia" in lowered else "AMD" if "amd" in lowered or "advanced micro" in lowered
              else "Intel" if "intel" in lowered else name.split(" ")[0])
    models = [b for b in re.findall(r"\[([^\]]+)\]", name) if b not in ("AMD/ATI",)]
    tail = name.rsplit("]", 1)[-1].strip() if "]" in name else ""
    model = models[-1] if models else tail
    pretty = f"{vendor} {model}".strip() if model else name
    return pretty, f"PCI {address} · {name}"


def _split_common(names: list[str], common: list[str]) -> tuple[list[str], list[str]]:
    first = [n for n in common if n in names]
    rest = [n for n in names if n not in first]
    return first, rest


def _wrap(items: list[str]) -> Adw.WrapBox:
    box = Adw.WrapBox(child_spacing=6, line_spacing=6)
    for item in items:
        box.append(w.chip(item))
    return box


def _chips_row(items: list[str], empty: str) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow(activatable=False)
    child = _wrap(items) if items else w.label(empty, css=("dimmed",))
    for side in ("top", "bottom", "start", "end"):
        getattr(child, f"set_margin_{side}")(12)
    row.set_child(child)
    return row


class SystemPage(Gtk.Box):
    title = "System & codecs"

    def __init__(self, on_rescan) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        versions = [
            f"Python {sys.version.split()[0]}",
            f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
            f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}",
        ]
        self.gst_missing: list[str] = []
        try:
            from .capture import Gst
        except Exception:  # noqa: BLE001 - optional media stack
            Gst = None
        if Gst is not None:
            versions.append(Gst.version_string())
            self.gst_missing = [n for n in GST_FACTORIES if not Gst.ElementFactory.find(n)]
        else:
            versions.append("GStreamer unavailable")
        self.version_box = _wrap(versions)
        self.ffmpeg_chip = w.chip("FFmpeg …")
        self.version_box.append(self.ffmpeg_chip)

        self.gpu_title = w.label(_("Detecting hardware…"), css=("title-3",))
        self.gpu_sub = w.label("", css=("sd-meta",), wrap=True)
        gpu_icon = Gtk.Image.new_from_icon_name("sd-system-symbolic")
        gpu_icon.set_pixel_size(40)
        gpu_icon.add_css_class("accent")
        gpu = Gtk.Box(spacing=16)
        gpu.append(gpu_icon)
        gpu.append(w.vbox(self.gpu_title, self.gpu_sub, spacing=2))
        hero = w.card(gpu, self.version_box, css="sd-hero", spacing=16)
        if self.gst_missing:
            hero.append(w.label(_("Unavailable GStreamer factories: ") + ", ".join(self.gst_missing)
                                + _(". Alternative decoders may be available."), css=("dimmed",), wrap=True))

        self.accel = w.group(_("Hardware acceleration"), _("Detected from ffmpeg -hwaccels and -encoders"))
        self._accel_rows: list[Gtk.Widget] = []
        self.status_label = w.label(_("Scanning…"), css=("dimmed",), wrap=True)

        ffmpeg = w.group("FFmpeg")
        self.command_row = w.action_row(_("Command"), _("detecting…"))
        self.command_row.set_subtitle_selectable(True)
        self.version_row = w.action_row(_("Version"), _("detecting…"))
        self.version_row.set_subtitle_selectable(True)
        ffmpeg.add(self.command_row)
        ffmpeg.add(self.version_row)
        self.error_label = w.notice("sd-notice")
        self.cpu = w.group(_("CPU video encoders"))
        self.audio = w.group(_("Audio encoders"))
        self._chip_rows: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []

        content = w.vbox(hero, self.error_label,
                         w.columns(w.vbox(self.accel, self.status_label, spacing=10),
                                   w.vbox(ffmpeg, self.cpu, self.audio, spacing=22), spacing=24),
                         spacing=22)
        self.dock_status = w.dock_status(_("Checking FFmpeg capabilities…"))
        self.rescan_button = w.label_button(_("Rescan"), "view-refresh-symbolic", css=("pill", "flat"),
                                            tooltip=_("Rescan FFmpeg capabilities"))
        self.rescan_button.connect("clicked", lambda *_: on_rescan())
        self.append(w.page_view(content, w.dock(self.dock_status, self.rescan_button), max_width=1400))

    def set_scanning(self, scanning: bool) -> None:
        self.rescan_button.set_sensitive(not scanning)
        if scanning:
            self.dock_status.set_text(_("Checking FFmpeg capabilities…"))

    def show_error(self, message: str) -> None:
        self.set_scanning(False)
        self.dock_status.set_text(_("Capability check failed"))
        self.error_label.set_text(_("Capability check failed: ") + message)

    def update(self, info, statuses, hardware, encoders) -> None:
        self.set_scanning(False)
        self.command_row.set_subtitle(" ".join(info.command) if info.command else _("(not found)"))
        self.version_row.set_subtitle(info.version_line or _("(unknown)"))
        self.ffmpeg_chip.set_text((info.version_line or "FFmpeg not found").split(" Copyright")[0])
        self.error_label.set_text(info.error or "")

        if not hardware.known:
            self.gpu_title.set_text(_("Hardware detection unavailable"))
            self.gpu_sub.set_text(hardware.error or "")
        elif hardware.gpu_lines:
            name, detail = _gpu_name(hardware.gpu_lines[0])
            others = [_gpu_name(line)[0] for line in hardware.gpu_lines[1:]]
            self.gpu_title.set_text(name)
            self.gpu_sub.set_text(" · ".join(filter(None, [detail] + ([_("also: ") + ", ".join(others)]
                                                                   if others else []))))
        else:
            self.gpu_title.set_text(_("No GPU detected"))
            self.gpu_sub.set_text(_("CPU encoders remain available."))

        for row in self._accel_rows:
            self.accel.remove(row)
        self._accel_rows.clear()
        usable = 0
        for status in statuses:
            usable += bool(status.usable)
            if status.usable:
                icon, css, text, kind = "emblem-ok-symbolic", "success", _("Ready"), "ok"
            elif status.ffmpeg_supported and status.hardware_available is False:
                icon, css, text, kind = "dialog-warning-symbolic", "warning", _("No hardware"), "warn"
            elif status.ffmpeg_supported:
                icon, css, text, kind = "dialog-question-symbolic", "dimmed", _("Hardware unknown"), None
            else:
                icon, css, text, kind = "window-close-symbolic", "dimmed", _("Not in FFmpeg"), None
            note = status.hardware_note or ""
            if status.matched:
                row = Adw.ExpanderRow(title=status.label, subtitle=note)
                row.add_row(_chips_row(list(status.matched), ""))
            else:
                row = w.action_row(status.label, note or None)
            image = Gtk.Image.new_from_icon_name(icon)
            image.add_css_class(css)
            row.add_prefix(image)
            row.add_suffix(w.pill(text, kind))
            self.accel.add(row)
            self._accel_rows.append(row)
        if info.command is None:
            self.status_label.set_text(_("FFmpeg not found. Install it or ensure it is in PATH."))
        else:
            self.status_label.set_text("")
        self.status_label.set_visible(bool(self.status_label.get_text()))

        for group, row in self._chip_rows:
            group.remove(row)
        self._chip_rows.clear()
        video = sorted({e.name for e in encoders if e.kind == "video" and NAME_RE.match(e.name)
                        and not e.name.endswith(HW_SUFFIXES)})
        audio = sorted({e.name for e in encoders if e.kind == "audio" and NAME_RE.match(e.name)})
        for group, names, common in ((self.cpu, video, COMMON_VIDEO), (self.audio, audio, COMMON_AUDIO)):
            first, rest = _split_common(names, common)
            row = _chips_row(first, _("None of the usual archive encoders reported"))
            group.add(row)
            self._chip_rows.append((group, row))
            if rest:
                more = Adw.ExpanderRow(title=_("All encoders"), subtitle=_("{count} more").format(count=len(rest)))
                more.add_row(_chips_row(rest, ""))
                group.add(more)
                self._chip_rows.append((group, more))

        self.dock_status.set_text(
            _("Ready · ") + (info.version_line or _("FFmpeg not found")).split(" Copyright")[0]
            + f" · {usable}/{len(statuses)} " + _("acceleration paths usable"))
