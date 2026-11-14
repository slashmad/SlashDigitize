import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk


class WorkflowTab(Gtk.Box):
    """Keep optional tooling out of startup; retain a tab's state once opened.

    Pages build their own scrolling page view with a pinned action dock."""
    def __init__(self, factory, *, audio=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.factory = factory
        self.audio = audio
        self.widget = None
        self.capabilities = None

    def activate(self):
        if self.widget is not None:
            return
        widget = self.factory()
        widget.set_vexpand(True)
        widget.set_hexpand(True)
        self.widget = widget
        self.append(widget)
        if self.capabilities:
            widget.sync_capabilities(**self.capabilities)

    def sync_capabilities(self, **kwargs):
        self.capabilities = kwargs
        if self.widget is not None:
            self.widget.sync_capabilities(**kwargs)

    def shutdown(self):
        if self.widget is not None and hasattr(self.widget, "shutdown"):
            self.widget.shutdown()
