from importlib.resources import files
import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk
from .video.i18n import setup_gettext


class DigitizeApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="se.slashmad.SlashDigitize")
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self._request_quit)
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _request_quit(self, *_args):
        # Every user Quit action traverses the same window close guard.
        for window in self.get_windows():
            window.close()

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        display = Gdk.Display.get_default()
        if os.environ.get("SLASHDIGITIZE_APPDIR"):
            # The portable bundle ships this theme. A host theme such as
            # Breeze may be selected by desktop settings but absent inside it.
            Gtk.Settings.get_for_display(display).set_property("gtk-icon-theme-name", "Adwaita")
        # App icon plus bundled symbolic icons, independent of the icon theme.
        Gtk.IconTheme.get_for_display(display).add_search_path(str(files("slashdigitize").joinpath("assets/icons")))
        provider = Gtk.CssProvider()
        provider.load_from_string(files("slashdigitize").joinpath("style.css").read_text())
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_provider = provider

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            from .video.gui import MainWindow
            window = MainWindow(self)
        window.present()


def main():
    setup_gettext()
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    return DigitizeApplication().run(None)
