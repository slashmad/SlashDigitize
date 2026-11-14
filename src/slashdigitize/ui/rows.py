"""Adw boxed-list rows with the small legacy API the workflow pages use.

The imported pages were written against GtkComboBoxText, GtkSpinButton,
GtkCheckButton and GtkEntry. These rows keep exactly the methods and signals
those pages call (see ``tests/test_rows.py``) so page logic stays unchanged
while the layout moves to libadwaita. Value rows carry the wheel guard: a
closed row never changes its value on mouse-wheel/touchpad scroll; the page
scrolls instead, and an open dropdown list scrolls normally.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402

from .widgets import guard_scroll  # noqa: E402
from slashdigitize.video.i18n import _  # noqa: E402

SEARCH_FROM = 12


class ChoiceRow(Adw.ComboRow):
    """Adw.ComboRow with the id-based GtkComboBoxText API.

    Semantics kept from GtkComboBox: rows start without an active item;
    ``append`` never changes the active item; ``remove_all`` clears it and
    emits ``changed`` only if something was active; ``set_active_id`` returns
    False and changes nothing for an unknown id; ``changed`` fires once per
    actual change of the active item, whether by code or by the user.

    The native Adw model has a disabled "Choose…" item at index0, because
    ComboRow cannot visually unset its selection. Native selected indices
    are offset by one; the legacy get/set_active API and get_model exclude
    that placeholder. This keeps the displayed and logical values aligned.
    """

    __gtype_name__ = "SdChoiceRow"
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, title: str = "", subtitle: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.set_use_markup(False)
        self.set_title(title)
        if subtitle:
            self.set_subtitle(subtitle)
        self._ids: list[str | None] = []
        self._model = Gtk.StringList()
        self._display_model = Gtk.StringList.new([_("Choose…")])
        self._placeholder = self._display_model.get_item(0)
        self._active = -1
        self._syncing = True
        self.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.set_factory(_ellipsizing_factory())
        self.set_list_factory(_list_factory(self._placeholder))
        self.set_model(self._display_model)
        self._syncing = False
        self._apply()
        self.connect("notify::selected", self._on_selected)
        guard_scroll(self)

    # ---- GtkComboBoxText API -------------------------------------------------
    def append(self, item_id: str | None, text: str) -> None:
        def add():
            self._ids.append(item_id)
            self._model.append(text)
            self._display_model.append(text)
        self._mutate(add)

    def append_text(self, text: str) -> None:
        self.append(None, text)

    def remove_all(self) -> None:
        had_active = self._active >= 0

        def clear():
            self._model.splice(0, self._model.get_n_items(), [])
            self._display_model.splice(1, len(self._ids), [])
            self._ids.clear()
            self._active = -1

        self._mutate(clear)
        if had_active:
            self.emit("changed")

    def get_active(self) -> int:
        return self._active

    def set_active(self, index: int) -> None:
        if index is None or index < 0 or index >= len(self._ids):
            index = -1
        if index == self._active:
            return
        self._active = index
        self._apply()
        self.emit("changed")

    def get_active_id(self) -> str | None:
        return self._ids[self._active] if self._active >= 0 else None

    def set_active_id(self, item_id: str | None) -> bool:
        if item_id is None:
            self.set_active(-1)
            return True
        try:
            index = self._ids.index(item_id)
        except ValueError:
            return False
        self.set_active(index)
        return True

    def get_active_text(self) -> str | None:
        return self._model.get_string(self._active) if self._active >= 0 else None

    def get_model(self):  # noqa: D401 - legacy callers only test for None
        return self._model

    def ids(self) -> list[str | None]:
        return list(self._ids)

    # ---- internals -------------------------------------------------------------
    def _mutate(self, change) -> None:
        self._syncing = True
        try:
            change()
        finally:
            self._syncing = False
        self.set_enable_search(self._model.get_n_items() >= SEARCH_FROM)
        self._apply()

    def _apply(self) -> None:
        target = self._active + 1
        if self.get_selected() != target:
            self._syncing = True
            try:
                self.set_selected(target)
            finally:
                self._syncing = False

    def _on_selected(self, *_args) -> None:
        if self._syncing:
            return
        selected = self.get_selected()
        index = selected - 1 if 0 < selected <= len(self._ids) else -1
        if index != self._active:
            self._active = index
            self.emit("changed")
        else:
            self._apply()


def _ellipsizing_factory() -> Gtk.SignalListItemFactory:
    """Selected value shown at the row end, ellipsized for long encoder names."""
    factory = Gtk.SignalListItemFactory()

    def setup(_f, item):
        label = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END, max_width_chars=28,
                          width_chars=4)
        item.set_child(label)

    def bind(_f, item):
        item.get_child().set_text(item.get_item().get_string())
        item.get_child().set_tooltip_text(item.get_item().get_string())

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


def _list_factory(placeholder) -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def setup(_f, item):
        label = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        item.set_child(label)

    def bind(_f, item):
        item.get_child().set_text(item.get_item().get_string())
        selectable = item.get_item() != placeholder
        item.set_selectable(selectable)
        item.set_activatable(selectable)
        item.get_child().set_sensitive(selectable)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


class SpinRow(Adw.ActionRow):
    """A boxed-list row around a Gtk.SpinButton (Adw.SpinRow is final).

    Keeps GtkSpinButton's API: ``value-changed``, ``get_value_as_int``,
    ``set_digits``, ``set_range``; the spin button carries the wheel guard."""

    __gtype_name__ = "SdSpinRow"
    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, title: str = "", lower: float = 0, upper: float = 100, step: float = 1,
                 value: float = 0, digits: int = 0, subtitle: str | None = None,
                 page: float | None = None, width_chars: int = 7):
        super().__init__(use_markup=False)
        self.set_title(title)
        if subtitle:
            self.set_subtitle(subtitle)
        adjustment = Gtk.Adjustment(lower=lower, upper=upper, step_increment=step,
                                    page_increment=page if page is not None else step * 10, value=value)
        self.spin = Gtk.SpinButton(adjustment=adjustment, digits=digits, numeric=True,
                                   valign=Gtk.Align.CENTER, width_chars=width_chars)
        self.spin.set_value(value)
        self.spin.connect("value-changed", lambda *_: self.emit("value-changed"))
        self.add_suffix(self.spin)
        self.set_activatable_widget(self.spin)
        guard_scroll(self.spin)
        guard_scroll(self)

    def get_value(self) -> float:
        return self.spin.get_value()

    def set_value(self, value: float) -> None:
        self.spin.set_value(value)

    def get_value_as_int(self) -> int:
        return self.spin.get_value_as_int()

    def set_digits(self, digits: int) -> None:
        self.spin.set_digits(digits)

    def get_digits(self) -> int:
        return self.spin.get_digits()

    def set_range(self, lower: float, upper: float) -> None:
        self.spin.set_range(lower, upper)

    def get_adjustment(self) -> Gtk.Adjustment:
        return self.spin.get_adjustment()


class SwitchRow(Adw.ActionRow):
    """A boxed-list row around a Gtk.Switch (Adw.SwitchRow is final),
    with GtkCheckButton's ``toggled``/``get_active``/``set_active``."""

    __gtype_name__ = "SdSwitchRow"
    __gsignals__ = {"toggled": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, title: str = "", subtitle: str | None = None, active: bool = False):
        super().__init__(use_markup=False)
        self.set_title(title)
        if subtitle:
            self.set_subtitle(subtitle)
        self.switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", lambda *_: self.emit("toggled"))
        self.add_suffix(self.switch)
        self.set_activatable_widget(self.switch)

    def get_active(self) -> bool:
        return self.switch.get_active()

    def set_active(self, active: bool) -> None:
        self.switch.set_active(active)


class EntryRow(Adw.EntryRow):
    """Adw.EntryRow with a GtkEntry-style placeholder hint.

    The hint is a dim suffix visible while the row is empty. Enter emits
    ``entry-activated`` (GtkEntry's ``activate`` is not reused because a
    ListBoxRow already has an ``activate`` signal)."""

    __gtype_name__ = "SdEntryRow"

    def __init__(self, title: str = "", text: str = "", placeholder: str | None = None):
        super().__init__()
        self.set_use_markup(False)
        self.set_title(title)
        self._hint = Gtk.Label(valign=Gtk.Align.CENTER)
        self._hint.add_css_class("dimmed")
        self.add_suffix(self._hint)
        self.set_text(text)
        self.set_placeholder_text(placeholder)
        self.connect("changed", lambda *_: self._sync_hint())

    def set_placeholder_text(self, text: str | None) -> None:
        self._hint.set_text(text or "")
        self._sync_hint()

    def get_placeholder_text(self) -> str:
        return self._hint.get_text()

    def _sync_hint(self) -> None:
        self._hint.set_visible(bool(self._hint.get_text()) and not self.get_text())


class PathRow(EntryRow):
    """An entry row for a file or folder path with a trailing browse button."""

    __gtype_name__ = "SdPathRow"

    def __init__(self, title: str, text: str = "", placeholder: str | None = None,
                 icon: str = "document-open-symbolic", tooltip: str = "Choose…"):
        super().__init__(title, text, placeholder)
        self.button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        self.button.add_css_class("flat")
        self.add_suffix(self.button)
