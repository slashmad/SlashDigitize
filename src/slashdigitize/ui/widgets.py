"""Builders and drawn widgets shared by every workflow page.

Presentation only: nothing here opens devices or starts processes. Meters
display whatever level observations a page feeds them.
"""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, GtkSource, Pango, PangoCairo  # noqa: E402

# --------------------------------------------------------------------------
# Wheel guard for value controls
# --------------------------------------------------------------------------


def _popover_open(widget: Gtk.Widget) -> bool:
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Popover) and child.get_visible():
            return True
        if _popover_open(child):
            return True
        child = child.get_next_sibling()
    return False


def forward_scroll(controller: Gtk.EventControllerScroll, _dx: float, dy: float, widget: Gtk.Widget) -> bool:
    """Scroll the page instead of the closed control under the pointer."""
    if _popover_open(widget):
        return False  # an open dropdown list scrolls normally
    scroller = widget.get_ancestor(Gtk.ScrolledWindow)
    if scroller is not None:
        adj = scroller.get_vadjustment()
        if controller.get_unit() == Gdk.ScrollUnit.WHEEL:
            delta = dy * adj.get_page_size() ** (2 / 3)  # same step GTK uses
        else:
            delta = dy
        top = adj.get_upper() - adj.get_page_size()
        adj.set_value(min(max(adj.get_value() + delta, adj.get_lower()), top))
    # Claim the event so the closed control never changes its value.
    return True


def guard_scroll(widget: Gtk.Widget) -> Gtk.Widget:
    """Closed dropdowns, spin rows and sliders scroll the page instead of
    changing their value. Explicit clicks and keyboard input still work."""
    controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)
    controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    controller.connect("scroll", forward_scroll, widget)
    widget.add_controller(controller)
    return widget


def scroll_guard_of(widget: Gtk.Widget) -> Gtk.EventControllerScroll | None:
    controllers = widget.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if (isinstance(controller, Gtk.EventControllerScroll)
                and controller.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE):
            return controller
    return None


# --------------------------------------------------------------------------
# Object registry used in place of GtkBuilder files
# --------------------------------------------------------------------------


class Layout:
    """Named widgets of a page, with the ``get_object`` API of Gtk.Builder."""

    def __init__(self) -> None:
        self.objects: dict[str, object] = {}

    def add(self, name: str, widget):
        if name in self.objects:
            raise ValueError(f"Duplicate layout object: {name}")
        self.objects[name] = widget
        return widget

    def get_object(self, name: str):
        return self.objects.get(name)


# --------------------------------------------------------------------------
# Small builders
# --------------------------------------------------------------------------


def toast(widget: Gtk.Widget, text: str, **kwargs) -> None:
    root = widget.get_root()
    if root is not None and hasattr(root, "toast"):
        root.toast(text, **kwargs)


def label(text: str = "", *, css: tuple[str, ...] = (), wrap: bool = False, xalign: float = 0,
          selectable: bool = False, ellipsize: bool = False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
    for name in css:
        lbl.add_css_class(name)
    return lbl


def pill(text: str, kind: str | None = None) -> Gtk.Label:
    lbl = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    lbl.add_css_class("sd-pill")
    if kind:
        lbl.add_css_class(kind)
    return lbl


def set_pill(lbl: Gtk.Label, text: str, kind: str | None) -> None:
    for name in ("ok", "warn", "error", "rec", "accent"):
        lbl.remove_css_class(name)
    if kind:
        lbl.add_css_class(kind)
    lbl.set_text(text)


def chip(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("sd-chip")
    return lbl


def caption(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text.upper(), xalign=0)
    lbl.add_css_class("sd-caption")
    return lbl


def group(title: str | None = None, description: str | None = None,
          suffix: Gtk.Widget | None = None) -> Adw.PreferencesGroup:
    grp = Adw.PreferencesGroup()
    if title:
        grp.set_title(GLib.markup_escape_text(title))
    if description:
        grp.set_description(GLib.markup_escape_text(description))
    if suffix is not None:
        grp.set_header_suffix(suffix)
    return grp


def action_row(title: str, subtitle: str | None = None, icon: str | None = None) -> Adw.ActionRow:
    row = Adw.ActionRow(use_markup=False)
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


def widget_row(title: str, widget: Gtk.Widget, subtitle: str | None = None) -> Adw.ActionRow:
    """A boxed-list row with an arbitrary control as suffix."""
    row = action_row(title, subtitle)
    widget.set_valign(Gtk.Align.CENTER)
    row.add_suffix(widget)
    return row


def icon_button(icon: str, tooltip: str, *, flat: bool = True, callback=None) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    if flat:
        button.add_css_class("flat")
    if callback:
        button.connect("clicked", lambda *_: callback())
    return button


def label_button(text: str, icon: str | None = None, *, css: tuple[str, ...] = ("pill",),
                 callback=None, tooltip: str | None = None) -> Gtk.Button:
    """A button whose ``set_label`` keeps the icon (Adw.ButtonContent)."""
    button = Gtk.Button(valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    if icon:
        button.set_child(Adw.ButtonContent(icon_name=icon, label=text, use_underline=True))
    else:
        button.set_label(text)
    for name in css:
        button.add_css_class(name)
    if callback:
        button.connect("clicked", lambda *_: callback())
    return button


def set_button_label(button: Gtk.Button, text: str, icon: str | None = None) -> None:
    child = button.get_child()
    if isinstance(child, Adw.ButtonContent):
        child.set_label(text)
        if icon:
            child.set_icon_name(icon)
    else:
        button.set_label(text)


def toggle_group(options: list[tuple[str, str]], active: str) -> Adw.ToggleGroup:
    tg = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
    for name, text in options:
        tg.add(Adw.Toggle(name=name, label=text))
    tg.set_active_name(active)
    return tg


def scale(lower: float, upper: float, step: float, value: float, *, digits: int = 2,
          width: int = 220, draw_value: bool = False) -> Gtk.Scale:
    widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
    widget.set_digits(digits)
    widget.set_value(value)
    widget.set_size_request(width, -1)
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_hexpand(True)
    widget.set_draw_value(draw_value)
    if draw_value:
        widget.set_value_pos(Gtk.PositionType.RIGHT)
    return guard_scroll(widget)


def source_buffer(language: str | None) -> GtkSource.Buffer:
    buffer = GtkSource.Buffer()
    if language:
        lang = GtkSource.LanguageManager.get_default().get_language(language)
        if lang is not None:
            buffer.set_language(lang)
    scheme = GtkSource.StyleSchemeManager.get_default().get_scheme("Adwaita-dark")
    if scheme is not None:
        buffer.set_style_scheme(scheme)
    return buffer


def code_view(text: str, language: str | None, *, title: str, editable: bool = False,
              min_height: int = 120, max_height: int = 420, line_numbers: bool = False,
              wrap: bool = True):
    """A monospace, syntax-highlighted card with a copy button.

    Returns (card, buffer, view); the view is a Gtk.TextView subclass."""
    buffer = source_buffer(language)
    buffer.set_text(text)
    view = GtkSource.View(buffer=buffer, monospace=True, editable=editable,
                          cursor_visible=editable, show_line_numbers=line_numbers,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR if wrap else Gtk.WrapMode.NONE)
    view.set_top_margin(10)
    view.set_bottom_margin(10)
    view.set_left_margin(14)
    view.set_right_margin(14)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("sd-code")
    header = Gtk.Box(spacing=6)
    header.add_css_class("sd-code-header")
    head_label = caption(title)
    head_label.set_hexpand(True)
    header.append(head_label)
    copy = icon_button("edit-copy-symbolic", "Copy to clipboard")

    def do_copy(*_):
        start, end = buffer.get_bounds()
        box.get_clipboard().set(buffer.get_text(start, end, False))
        toast(box, f"{title[:1].upper()}{title[1:].lower()} copied")

    copy.connect("clicked", do_copy)
    header.append(copy)
    box.append(header)
    scroller = Gtk.ScrolledWindow(min_content_height=min_height, propagate_natural_height=True,
                                  max_content_height=max_height)
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.set_child(view)
    box.append(scroller)
    box.header = header
    return box, buffer, view


def columns(*children: Gtk.Widget, spacing: int = 18, homogeneous: bool = True) -> Gtk.Box:
    """Side by side on wide pages, stacked when narrow (see ``page_view``)."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, homogeneous=homogeneous)
    box.add_css_class("sd-columns")
    for child in children:
        child.set_hexpand(True)
        child.set_valign(Gtk.Align.START)
        box.append(child)
    return box


def vbox(*children: Gtk.Widget, spacing: int = 18) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for child in children:
        box.append(child)
    return box


def hbox(*children: Gtk.Widget, spacing: int = 8) -> Gtk.Box:
    box = Gtk.Box(spacing=spacing)
    for child in children:
        box.append(child)
    return box


def _descendants(widget: Gtk.Widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


STACK_BELOW_SP = 940


def page_view(content: Gtk.Widget, dock: Gtk.Widget | None = None,
              banner: Gtk.Widget | None = None, max_width: int = 1240) -> Adw.BreakpointBin:
    """Scrollable, width-clamped page with an optional pinned action dock.

    Column boxes created with ``columns`` stack vertically when the page
    itself (not the window) is narrower than ``STACK_BELOW_SP``."""
    content.add_css_class("sd-page")
    content.add_css_class("sd-groups")
    clamp = Adw.Clamp(maximum_size=max_width, tightening_threshold=max_width - 200)
    clamp.set_child(content)
    scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_child(clamp)
    view = Adw.ToolbarView(content=scroller)
    if banner is not None:
        view.add_top_bar(banner)
    if dock is not None:
        view.add_bottom_bar(dock)
        view.set_bottom_bar_style(Adw.ToolbarStyle.RAISED_BORDER)
    bin_ = Adw.BreakpointBin(child=view, hexpand=True, vexpand=True)
    bin_.set_size_request(340, 320)
    narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {STACK_BELOW_SP}sp"))
    from gi.repository import GObject
    vertical = GObject.Value(Gtk.Orientation, Gtk.Orientation.VERTICAL)
    for widget in _descendants(content):
        if isinstance(widget, Gtk.Box) and widget.has_css_class("sd-columns"):
            narrow.add_setter(widget, "orientation", vertical)
            narrow.add_setter(widget, "homogeneous", False)
    bin_.add_breakpoint(narrow)
    bin_.scroller = scroller
    return bin_


def dock(status: Gtk.Widget, *buttons: Gtk.Widget) -> Gtk.Box:
    bar = Gtk.Box(spacing=10)
    bar.add_css_class("sd-dock")
    status.set_hexpand(True)
    bar.append(status)
    for button in buttons:
        bar.append(button)
    return bar


def dock_status(text: str = "") -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.END)
    lbl.add_css_class("sd-dock-status")
    return lbl


def card(*children: Gtk.Widget, css: str = "sd-card", spacing: int = 12) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class(css)
    for child in children:
        box.append(child)
    return box


def notice(css: str = "dimmed") -> Gtk.Label:
    """A wrapped status/hint label that hides itself while empty."""
    lbl = Gtk.Label(xalign=0, wrap=True, visible=False)
    lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    lbl.add_css_class(css)
    lbl.connect("notify::label", lambda w, *_: w.set_visible(bool(w.get_label().strip())))
    return lbl


class TextDialog:
    """A reusable, non-modal Adw.Dialog around an existing text view
    (logs and queues keep appending while it is closed)."""

    def __init__(self, title: str, child: Gtk.Widget, width: int = 900, height: int = 520):
        self.title = title
        self.child = child
        self.width = width
        self.height = height
        self.dialog: Adw.Dialog | None = None

    def present(self, parent: Gtk.Widget) -> None:
        if self.dialog is not None:
            self.dialog.present(parent)
            return
        header = Adw.HeaderBar()
        view = Adw.ToolbarView(content=self.child)
        view.add_top_bar(header)
        self.dialog = Adw.Dialog(title=self.title, child=view, content_width=self.width,
                                 content_height=self.height)
        self.dialog.present(parent)

    def close(self) -> None:
        if self.dialog is not None:
            self.dialog.close()

    def is_open(self) -> bool:
        return self.dialog is not None and self.dialog.get_parent() is not None


def log_view(min_height: int = 260):
    """A monospace scrolling log; returns (scroller, view)."""
    view = GtkSource.View(buffer=source_buffer(None), monospace=True, editable=False,
                          cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    for side in ("top", "bottom"):
        getattr(view, f"set_{side}_margin")(10)
    view.set_left_margin(14)
    view.set_right_margin(14)
    view.add_css_class("sd-log")
    scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=min_height)
    scroller.set_child(view)
    return scroller, view


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _hex(color: str, alpha: float = 1.0):
    color = color.lstrip("#")
    return (int(color[0:2], 16) / 255, int(color[2:4], 16) / 255, int(color[4:6], 16) / 255, alpha)


GREEN, YELLOW, RED, VIOLET = "#3ccf91", "#f2c94b", "#ff4652", "#8a4fd8"
FLOOR_DB = -120.0


def iec_scale(db: float) -> float:
    """IEC 60268-18 style deflection, 0..1 for -70..0 dBFS."""
    if db < -70:
        v = 0.0
    elif db < -60:
        v = (db + 70) * 0.25
    elif db < -50:
        v = (db + 60) * 0.5 + 2.5
    elif db < -40:
        v = (db + 50) * 0.75 + 7.5
    elif db < -30:
        v = (db + 40) * 1.5 + 15
    elif db < -20:
        v = (db + 30) * 2.0 + 30
    else:
        v = (db + 20) * 2.5 + 50
    return max(0.0, min(1.0, v / 100))


def _text(widget, cr, text, x, y, *, size=8.0, bold=False, align=0.0, alpha=0.55, color=None):
    layout = widget.create_pango_layout(text)
    desc = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
    desc.set_absolute_size(size * 1.333 * Pango.SCALE)
    layout.set_font_description(desc)
    w, h = layout.get_pixel_size()
    if color is None:
        fg = widget.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
    else:
        cr.set_source_rgba(*color)
    cr.move_to(x - w * align, y - h / 2)
    PangoCairo.show_layout(cr, layout)
    return w


def clamp_db(value: float) -> float:
    if value is None or math.isnan(value):
        return FLOOR_DB
    return max(FLOOR_DB, min(0.0, value))


# --------------------------------------------------------------------------
# Stereo meter
# --------------------------------------------------------------------------


class StereoMeter(Gtk.DrawingArea):
    """Segmented L/R dBFS meter with peak hold and latched clip LEDs.

    The values are display smoothing of the level observations a page
    feeds (arecord's VU percentages for audio recording), so this is not a
    true-peak or loudness meter. Animation runs only while levels move."""

    RELEASE_DB_S = 26.0
    HOLD_S = 1.6
    PEAK_FALL_DB_S = 18.0
    # Match the recorder's >=100% VU observation. Near full scale is not
    # evidence of clipping; neither this nor arecord's VU is true-peak DSP.
    CLIP_DB = 0.0
    TICKS = (-60, -48, -36, -24, -18, -12, -9, -6, -3, 0)

    def __init__(self, compact: bool = False, channels: int = 2):
        super().__init__(hexpand=True)
        self.compact = compact
        self.channels = channels
        self.set_content_height((30 if channels == 2 else 18) if compact else 64)
        self.target = [FLOOR_DB] * 2
        self.display = [FLOOR_DB] * 2
        self.peak = [FLOOR_DB] * 2
        self.peak_at = [0.0, 0.0]
        self.clip = [False, False]
        self._tick_id = 0
        self._last = None
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.reset_clip())
        self.add_controller(click)
        self.set_tooltip_text("Click to reset the clip indicators")
        self.connect("unmap", lambda *_: self._stop_tick())
        self.connect("map", lambda *_: self._start_tick())

    def set_levels(self, left: float, right: float | None = None) -> None:
        right = left if right is None else right
        self.target = [clamp_db(left), clamp_db(right)]
        for i, value in enumerate(self.target):
            if value >= self.CLIP_DB:
                self.clip[i] = True
        self._start_tick()

    def silence(self) -> None:
        self.target = [FLOOR_DB, FLOOR_DB]
        self._start_tick()

    def reset(self) -> None:
        self.target = [FLOOR_DB, FLOOR_DB]
        self.display = [FLOOR_DB, FLOOR_DB]
        self.peak = [FLOOR_DB, FLOOR_DB]
        self.clip = [False, False]
        self.queue_draw()

    def reset_clip(self) -> None:
        self.clip = [False, False]
        self.queue_draw()

    def any_clip(self) -> bool:
        return any(self.clip)

    def _start_tick(self):
        if not self._tick_id and self.get_mapped():
            self._last = None
            self._tick_id = self.add_tick_callback(self._on_tick)
        elif not self.get_mapped():
            self.display = list(self.target)

    def _stop_tick(self):
        if self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0

    def _on_tick(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = 0.016 if self._last is None else min(0.1, now - self._last)
        self._last = now
        busy = False
        for i in range(2):
            t = self.target[i]
            if t >= self.display[i]:
                self.display[i] = t
            else:
                self.display[i] = max(t, self.display[i] - self.RELEASE_DB_S * dt)
            if self.display[i] >= self.peak[i]:
                self.peak[i] = self.display[i]
                self.peak_at[i] = now
            elif now - self.peak_at[i] > self.HOLD_S:
                self.peak[i] = max(FLOOR_DB, self.peak[i] - self.PEAK_FALL_DB_S * dt)
            if self.display[i] > -90 or self.peak[i] > -90 or t > -90:
                busy = True
        self.queue_draw()
        if not busy:
            self._tick_id = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, width, height):
        label_w = 16
        value_w = 0 if self.compact else 54
        clip_w = 30 if self.compact else 40
        x0 = label_w
        bar_w = width - label_w - value_w - clip_w - 10
        if bar_w < 40:
            return
        if self.compact:
            bar_h, gap = 11, 6
            if self.channels == 1:
                ys = [(height - bar_h) / 2]
            else:
                ys = [(height - 2 * bar_h - gap) / 2, (height - 2 * bar_h - gap) / 2 + bar_h + gap]
        else:
            bar_h, scale_h = 15, 22
            top = (height - 2 * bar_h - scale_h) / 2
            ys = [top, top + bar_h + scale_h]
        seg_w, seg_gap = 3.0, 1.6
        n = int(bar_w // (seg_w + seg_gap))
        f_yellow, f_red = iec_scale(-18), iec_scale(-6)
        names = "LR" if self.channels == 2 else "·"
        for ch, y in enumerate(ys):
            _text(self, cr, names[ch], 2, y + bar_h / 2, size=8.5, bold=True, alpha=0.6)
            lit = iec_scale(self.display[ch])
            for i in range(n):
                f = (i + 0.5) / n
                color = GREEN if f < f_yellow else YELLOW if f < f_red else RED
                cr.set_source_rgba(*_hex(color, 1.0 if f <= lit else 0.11))
                _rounded(cr, x0 + i * (seg_w + seg_gap), y, seg_w, bar_h, 1.2)
                cr.fill()
            if self.peak[ch] > -70:
                pf = iec_scale(self.peak[ch])
                px = x0 + pf * (n * (seg_w + seg_gap)) - 2
                color = GREEN if pf < f_yellow else YELLOW if pf < f_red else RED
                cr.set_source_rgba(*_hex(color))
                _rounded(cr, px, y - 2, 3, bar_h + 4, 1.5)
                cr.fill()
            if not self.compact:
                value = self.peak[ch]
                text = "−∞" if value <= -70 else f"{value:+.1f}".replace("-", "−")
                _text(self, cr, text, x0 + bar_w + 10 + value_w - 6, y + bar_h / 2,
                      size=9, bold=True, align=1.0, alpha=0.85)
            cx = width - clip_w
            _rounded(cr, cx, y, clip_w, bar_h, 4)
            if self.clip[ch]:
                cr.set_source_rgba(*_hex(RED))
                cr.fill()
                _text(self, cr, "CLIP", cx + clip_w / 2, y + bar_h / 2, size=7, bold=True,
                      align=0.5, color=(1, 1, 1, 1))
            else:
                cr.set_source_rgba(1, 1, 1, 0.06)
                cr.fill()
                _text(self, cr, "CLIP", cx + clip_w / 2, y + bar_h / 2, size=7, bold=True,
                      align=0.5, alpha=0.25)
        if not self.compact:
            span = n * (seg_w + seg_gap)
            mid = ys[0] + bar_h + (ys[1] - ys[0] - bar_h) / 2
            for db in self.TICKS:
                x = x0 + iec_scale(db) * span
                cr.set_source_rgba(1, 1, 1, 0.18)
                cr.rectangle(x - 0.5, ys[0] + bar_h + 2, 1, 3)
                cr.rectangle(x - 0.5, ys[1] - 5, 1, 3)
                cr.fill()
                _text(self, cr, str(db).replace("-", "−"), x, mid, size=7.5, align=0.5, alpha=0.45)
            _text(self, cr, "dBFS", x0 + bar_w + 10 + value_w - 6, mid, size=7, align=1.0, alpha=0.4)


# --------------------------------------------------------------------------
# Level history strip
# --------------------------------------------------------------------------


class LevelHistory(Gtk.DrawingArea):
    """Mirrored L/R envelope of recent meter values (not of audio samples)."""

    def __init__(self, seconds: int = 60, rate: int = 4):
        super().__init__(hexpand=True)
        self.set_content_height(74)
        self.capacity = seconds * rate
        self.seconds = seconds
        self.values: list[tuple[float, float]] = []
        self.set_draw_func(self._draw)

    def push(self, left: float, right: float) -> None:
        self.values.append((clamp_db(left), clamp_db(right)))
        if len(self.values) > self.capacity:
            del self.values[: len(self.values) - self.capacity]
        self.queue_draw()

    def clear(self) -> None:
        self.values.clear()
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        mid = height / 2
        half = mid - 10
        cr.set_source_rgba(1, 1, 1, 0.05)
        _rounded(cr, 0, 0, width, height, 10)
        cr.fill()
        for db in (-18, -6):
            off = iec_scale(db) * half
            cr.set_source_rgba(*_hex(YELLOW if db == -18 else RED, 0.16))
            cr.set_dash([3, 4])
            cr.set_line_width(1)
            for y in (mid - off, mid + off):
                cr.move_to(0, y)
                cr.line_to(width, y)
            cr.stroke()
        cr.set_dash([])
        cr.set_source_rgba(1, 1, 1, 0.12)
        cr.rectangle(0, mid - 0.5, width, 1)
        cr.fill()
        step = width / self.capacity
        start = width - len(self.values) * step
        hot = iec_scale(-6)
        for i, (left, right) in enumerate(self.values):
            x = start + i * step
            for value, sign in ((left, -1), (right, 1)):
                f = iec_scale(value)
                if f <= 0:
                    continue
                color = RED if f >= hot else VIOLET
                cr.set_source_rgba(*_hex(color, 0.9 if color == RED else 0.75))
                h = f * half
                cr.rectangle(x, mid - h if sign < 0 else mid, max(step - 0.4, 0.6), h)
                cr.fill()
        _text(self, cr, f"−{self.seconds} s", 8, height - 7, size=7, alpha=0.35)
        _text(self, cr, "now", width - 8, height - 7, size=7, align=1.0, alpha=0.35)
        _text(self, cr, "L", 8, 9, size=7, bold=True, alpha=0.35)
        _text(self, cr, "R", 8, height - 18, size=7, bold=True, alpha=0.35)


def fmt_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
