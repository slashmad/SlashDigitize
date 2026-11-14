"""Legacy-API rows: ComboBoxText/SpinButton/CheckButton semantics on Adw rows.

Needs a display; scripts/smoke.py runs it on a private headless Weston. The
plain unit-test run skips it when no display is available.
"""
import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

HAVE_DISPLAY = Gtk.init_check() and Gdk.Display.get_default() is not None


@unittest.skipUnless(HAVE_DISPLAY, "needs a display (run scripts/smoke.py)")
class ChoiceRowTests(unittest.TestCase):
    def setUp(self):
        Adw.init()
        from slashdigitize.ui.rows import ChoiceRow
        self.row = ChoiceRow("Codec")
        self.changes = []
        self.row.connect("changed", lambda row: self.changes.append(row.get_active_id()))

    def test_empty_row_has_no_selection(self):
        self.assertEqual(self.row.get_active(), -1)
        self.assertIsNone(self.row.get_active_id())
        self.assertIsNone(self.row.get_active_text())
        self.assertIsNotNone(self.row.get_model())

    def test_append_does_not_select_or_signal(self):
        self.row.append("a", "Alpha")
        self.row.append("b", "Beta")
        self.assertIsNone(self.row.get_active_id())
        self.assertEqual(self.changes, [])
        self.assertEqual(self.row.get_selected(), 0)  # visible unset placeholder
        self.assertEqual(self.row.get_selected_item().get_string(), "Choose…")
        self.assertEqual(self.row.get_model().get_n_items(), 2)  # legacy model

    def test_set_active_id_known_and_unknown(self):
        self.row.append("a", "Alpha")
        self.row.append("b", "Beta")
        self.assertTrue(self.row.set_active_id("b"))
        self.assertEqual(self.row.get_active_text(), "Beta")
        self.assertFalse(self.row.set_active_id("zzz"))
        self.assertEqual(self.row.get_active_id(), "b")
        self.assertEqual(self.changes, ["b"])
        self.assertTrue(self.row.set_active_id("b"))
        self.assertEqual(self.changes, ["b"], "re-selecting the same id must not signal")

    def test_duplicate_labels_keep_distinct_ids(self):
        self.row.append("hw:1,0", "USB Audio")
        self.row.append("hw:2,0", "USB Audio")
        self.row.set_active_id("hw:2,0")
        self.assertEqual(self.row.get_active(), 1)
        self.assertEqual(self.row.get_active_id(), "hw:2,0")

    def test_rebuild_keeps_id_without_transient_other_selection(self):
        for key in ("a", "b", "c"):
            self.row.append(key, key.upper())
        self.row.set_active_id("c")
        self.changes.clear()
        self.row.remove_all()
        for key in ("x", "c", "a"):
            self.row.append(key, key.upper())
        self.row.set_active_id("c")
        # Only the clear and the explicit re-select: never "x" or "a".
        self.assertEqual(self.changes, [None, "c"])
        self.assertEqual(self.row.get_active(), 1)

    def test_remove_all_on_empty_selection_is_silent(self):
        self.row.append("a", "Alpha")
        self.row.remove_all()
        self.assertEqual(self.changes, [])

    def test_user_selection_emits_changed(self):
        self.row.append("a", "Alpha")
        self.row.append("b", "Beta")
        self.row.set_selected(2)  # placeholder0, Alpha1, Beta2
        self.assertEqual(self.changes, ["b"])
        self.assertEqual(self.row.get_active_id(), "b")

    def test_first_popup_item_activation_sets_logical_id(self):
        from slashdigitize.ui.widgets import _descendants
        self.row.append("a", "Alpha")
        self.row.append("b", "Beta")
        # Exercise the real popup's activation path, including its initial
        # selection, rather than only a programmatic legacy setter.
        lists = [child for child in _descendants(self.row)
                 if isinstance(child, Gtk.ListView) and child.get_model().get_n_items() == 3]
        self.assertEqual(len(lists), 1)
        for view in lists:
            # GTK selects the clicked item before emitting activate. The
            # selected-value presentation is a separate one-item ListView.
            view.get_model().set_selected(1)
            view.emit("activate", 1)
        self.assertEqual(self.row.get_active_id(), "a")
        self.assertEqual(self.changes, ["a"])

    def test_single_item_can_be_chosen_after_clear(self):
        self.row.append("old", "Old")
        self.row.set_active_id("old")
        self.row.remove_all()
        self.row.append("only", "Only")
        self.changes.clear()
        self.assertEqual(self.row.get_selected(), 0)
        self.assertIsNone(self.row.get_active_id())
        self.row.set_selected(1)
        self.assertEqual(self.row.get_active_id(), "only")
        self.assertEqual(self.changes, ["only"])

    def test_explicit_unset_displays_placeholder(self):
        self.row.append("a", "Alpha")
        self.row.set_active_id("a")
        self.row.set_active(-1)
        self.assertIsNone(self.row.get_active_text())
        self.assertEqual(self.row.get_selected(), 0)
        self.assertEqual(self.row.get_selected_item().get_string(), "Choose…")
        self.row.set_selected(1)
        self.assertEqual(self.changes, ["a", None, "a"])

    def test_set_active_index_and_out_of_range(self):
        self.row.append("a", "Alpha")
        self.row.set_active(0)
        self.row.set_active(7)
        self.assertEqual(self.changes, ["a", None])

    def test_insensitive_row_still_reports_value(self):
        self.row.append("a", "Alpha")
        self.row.set_active_id("a")
        self.row.set_sensitive(False)
        self.assertEqual(self.row.get_active_id(), "a")

    def test_closed_row_wheel_is_claimed_without_change(self):
        from slashdigitize.ui.widgets import forward_scroll, scroll_guard_of
        self.row.append("a", "Alpha")
        self.row.append("b", "Beta")
        self.row.set_active_id("a")
        controller = scroll_guard_of(self.row)
        self.assertIsNotNone(controller)
        self.assertTrue(forward_scroll(controller, 0, 3, self.row))
        self.assertEqual(self.row.get_active_id(), "a")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display (run scripts/smoke.py)")
class ValueRowTests(unittest.TestCase):
    def setUp(self):
        Adw.init()

    def test_spin_row_value_changed_and_int(self):
        from slashdigitize.ui.rows import SpinRow
        row = SpinRow("Rate", 8000, 192000, 1000, 48000)
        seen = []
        row.connect("value-changed", lambda r: seen.append(r.get_value_as_int()))
        row.set_value(44100)
        self.assertEqual(seen, [44100])
        row.set_digits(1)
        self.assertEqual(row.get_value_as_int(), 44100)

    def test_switch_row_toggled(self):
        from slashdigitize.ui.rows import SwitchRow
        row = SwitchRow("Match FPS", active=True)
        seen = []
        row.connect("toggled", lambda r: seen.append(r.get_active()))
        row.set_active(False)
        self.assertEqual(seen, [False])

    def test_entry_row_placeholder_hint(self):
        from slashdigitize.ui.rows import EntryRow
        row = EntryRow("Bitrate", placeholder="6M")
        self.assertEqual(row.get_placeholder_text(), "6M")
        self.assertTrue(row._hint.get_visible())
        row.set_text("8M")
        self.assertFalse(row._hint.get_visible())
        self.assertEqual(row.get_text(), "8M")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display (run scripts/smoke.py)")
class MeterTests(unittest.TestCase):
    def test_vu_clip_boundary_and_latch(self):
        from slashdigitize.audio.core import percent_to_dbfs
        from slashdigitize.ui.widgets import StereoMeter
        meter = StereoMeter()
        for percent in (0, 50, 98, 99):
            meter.set_levels(percent_to_dbfs(percent), percent_to_dbfs(50))
            self.assertFalse(meter.any_clip(), f"{percent}% must not indicate clipping")
        meter.set_levels(percent_to_dbfs(100), percent_to_dbfs(50))
        self.assertTrue(meter.any_clip())
        meter.set_levels(percent_to_dbfs(50), percent_to_dbfs(50))
        self.assertTrue(meter.any_clip(), "clip history must survive quieter input")
        meter.reset_clip()
        self.assertFalse(meter.any_clip())


if __name__ == "__main__":
    unittest.main()
