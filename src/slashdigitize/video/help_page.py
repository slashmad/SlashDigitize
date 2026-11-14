"""Help: workflows, recording safety rules and the project README."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402

WORKFLOWS = [
    ("audio", "sd-audio-symbolic", "Audio recording",
     "Direct ALSA arecord, 48 kHz / 32-bit stereo WAV, meters, XRUN and clip reporting."),
    ("capture", "sd-video-symbolic", "Video capture", "V4L2 capture with FFmpeg profiles and a GStreamer live view."),
    ("trim", "sd-trim-symbolic", "Trim & export", "Trim, fix audio sync and picture, export or stream-copy."),
    ("timelapse", "sd-timelapse-symbolic", "Timelapse", "Image sequences and RAW previews to bounded video."),
    ("vapoursynth", "sd-vapoursynth-symbolic", "VapourSynth", "Deinterlacing and cleanup pipelines with a job queue."),
    ("vsrepo", "sd-plugins-symbolic", "Filter plugins", "Discover and set up VapourSynth packages via VSRepo."),
    ("hardware", "sd-system-symbolic", "System & codecs", "FFmpeg build, GPU encoders and acceleration paths."),
]
SAFETY = [
    ("document-save-symbolic", "Existing recordings are never overwritten",
     "Recording refuses to start if the target file already exists."),
    ("media-playback-stop-symbolic", "Stop finalizes the file",
     "Stop sends SIGINT and waits for arecord to write a valid WAV header. There is no forced kill."),
    ("window-close-symbolic", "Closing is blocked while work runs",
     "Close, the menu and Ctrl+Q all ask you to stop recordings, probes and exports first."),
    ("audio-input-microphone-symbolic", "No silent audio fallback",
     "Audio uses the chosen hw: device only — never PipeWire, PulseAudio or ALSA plugins."),
    ("dialog-warning-symbolic", "XRUNs mean missing samples",
     "The recorder survives an XRUN, but the lost audio is not recovered. Archival takes need XRUN 0."),
]


def load_readme_text() -> str:
    here = os.path.dirname(__file__)
    candidates = [
        os.path.abspath(os.path.join(here, "..", "README.md")),
        os.path.abspath(os.path.join(here, "..", "..", "..", "README.md")),
        "/app/share/doc/slashdigitize/README.md",
        "/usr/share/doc/slashdigitize/README.md",
    ]
    for path in candidates:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as handle:
                    return handle.read()
        except OSError:
            continue
    return _("README not found. If you're running from source, open README.md in the project root.")


class HelpPage(Gtk.Box):
    def __init__(self, navigate) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        icon = Gtk.Image.new_from_icon_name("se.slashmad.SlashDigitize")
        icon.set_pixel_size(112)
        name = Gtk.Label(label="SlashDigitize")
        name.add_css_class("title-1")
        lead = Gtk.Label(label=_("A dark GTK4 workstation for digitizing tapes — audio, video, timelapse."),
                         wrap=True, justify=Gtk.Justification.CENTER)
        lead.add_css_class("dimmed")
        hero = w.vbox(icon, name, lead, spacing=8)
        hero.add_css_class("sd-help-hero")

        flows = w.group(_("Workflows"))
        for page, icon_name, title, text in WORKFLOWS:
            row = w.action_row(_(title), _(text))
            row.set_activatable(True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda _r, p=page: navigate(p))
            flows.add(row)

        safety = w.group(_("Recording safety"), _("These rules protect irreplaceable tapes"))
        for icon_name, title, text in SAFETY:
            row = w.action_row(_(title), _(text))
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            safety.add(row)

        run, _b, _v = w.code_view("PYTHONPATH=src python3 -m slashdigitize", "sh",
                                  title=_("Run from source"), min_height=40)

        readme_text = load_readme_text()
        readme, self.help_buffer, self.help_view = w.code_view(readme_text, "markdown", title="README.md",
                                                              min_height=320, max_height=640)
        readme_expander = Gtk.Expander(label=_("Project README"), child=readme)
        readme_expander.get_child().set_margin_top(10)

        more = w.group()
        shortcuts = Adw.ButtonRow(title=_("Keyboard Shortcuts"), start_icon_name="input-keyboard-symbolic")
        shortcuts.set_action_name("win.shortcuts")
        about = Adw.ButtonRow(title=_("About SlashDigitize"), start_icon_name="help-about-symbolic")
        about.set_action_name("win.about")
        more.add(shortcuts)
        more.add(about)

        content = w.vbox(hero, flows, safety, run, readme_expander, more, spacing=24)
        self.append(w.page_view(content, max_width=820))
