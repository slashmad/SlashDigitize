"""Layout of the VSRepo / filter plugin page (replaces vapoursynth_page.ui)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from slashdigitize.ui import widgets as w  # noqa: E402
from slashdigitize.ui.rows import ChoiceRow  # noqa: E402
from slashdigitize.video.capture_layout import RowSubtitle  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402


def _tile(L: w.Layout, name: str, title: str, css: str | None) -> Gtk.Box:
    value = L.add(name, w.label("—", css=("sd-stat-value",) + ((css,) if css else ())))
    return w.card(w.caption(title), value, spacing=2)


def build() -> w.Layout:
    L = w.Layout()
    tiles = Gtk.Box(spacing=14, homogeneous=True)
    tiles.append(_tile(L, "tile_installed", _("Installed"), "ok"))
    tiles.append(_tile(L, "tile_missing", _("Missing"), "error"))
    tiles.append(_tile(L, "tile_nolinux", _("No Linux build"), "warn"))
    tiles.append(_tile(L, "tile_unknown", _("Unknown"), None))

    env = w.group(_("Environment"))
    status_row = w.action_row(_("VapourSynth"), _("Checking…"))
    status_row.set_subtitle_selectable(True)
    L.add("vs_status_label", RowSubtitle(status_row))
    refresh = L.add("vs_refresh_button", w.icon_button("view-refresh-symbolic", _("Refresh")))
    env.set_header_suffix(refresh)
    env.add(status_row)
    paths_row = w.action_row(_("Paths"), "")
    paths_row.set_subtitle_selectable(True)
    L.add("vs_paths_label", RowSubtitle(paths_row))
    env.add(paths_row)
    plugins_row = w.action_row(_("Loaded plugins"), "")
    plugins_row.set_subtitle_selectable(True)
    L.add("vs_plugins_label", RowSubtitle(plugins_row))
    env.add(plugins_row)

    preset = w.group(_("Target preset"))
    combo = L.add("preset_combo", ChoiceRow(_("Preset")))
    L.add("preset_description_label", RowSubtitle(combo))
    preset.add(combo)
    summary = L.add("preset_summary_label", w.label("", css=("sd-meta",), wrap=True))

    packages = L.add("package_list", Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE))
    packages.add_css_class("boxed-list")
    placeholder = w.label(_("No packages resolved for this preset."), css=("dimmed",))
    for side in ("top", "bottom", "start", "end"):
        getattr(placeholder, f"set_margin_{side}")(18)
    packages.set_placeholder(placeholder)
    package_group = w.group(_("Packages"), _("Resolved dependencies of the preset"))
    package_group.add(packages)
    L.add("filters_view", Gtk.TextView())  # plain-text status kept for copy/export

    install, _ibuf, install_view = w.code_view("", "sh", title=_("Install command"), min_height=110)
    L.add("install_command_view", install_view)
    notes = L.add("install_notes_label", w.label("", css=("dimmed",), wrap=True))
    codecs, _cbuf, codec_view = w.code_view("", None, title=_("FFmpeg export support"), min_height=110)
    L.add("codec_support_view", codec_view)

    left = w.vbox(preset, summary, package_group, spacing=12)
    right = w.vbox(install, notes, codecs, spacing=12)
    content = w.vbox(tiles, env, w.columns(left, right, spacing=24), spacing=22)
    dock_status = L.add("dock_status", w.dock_status(_("VSRepo installs nothing from here; copy the command")))
    L.add("vapoursynth_page_root", w.page_view(content, w.dock(dock_status), max_width=1400))
    return L
