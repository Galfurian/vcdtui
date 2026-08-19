"""The cursor-driven value-format menu.

The menu contents come from a pure function, so qualification never has to
simulate terminal keystrokes.
"""

import unittest

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$var reg 4 " count [3:0] $end
$upscope $end
$enddefinitions $end
#0
0!
b0 "
"""


class MenuIndexTests(unittest.TestCase):
    def test_moves_within_bounds(self):
        self.assertEqual(vcdtui.move_menu_index(0, 4, 1), 1)
        self.assertEqual(vcdtui.move_menu_index(2, 4, -1), 1)

    def test_wraps_around_both_ends(self):
        self.assertEqual(vcdtui.move_menu_index(3, 4, 1), 0)
        self.assertEqual(vcdtui.move_menu_index(0, 4, -1), 3)

    def test_empty_menu_stays_at_zero(self):
        self.assertEqual(vcdtui.move_menu_index(0, 0, 1), 0)


class ValueFormatMenuTests(unittest.TestCase):
    def setUp(self):
        vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.signal = next(s for s in vcd.signals if s.reference == "count")

    def lines(self, current, highlighted, ascii_only=True):
        return vcdtui.value_format_menu_lines(
            self.signal, current, highlighted, ascii_only=ascii_only
        )

    def test_menu_offers_every_display_format_in_order(self):
        names = [name for name, _ in vcdtui.VALUE_FORMAT_CHOICES]
        self.assertEqual(tuple(names), vcdtui._DISPLAY_FORMATS)

    def test_menu_titles_the_focused_signal(self):
        self.assertIn("count[3:0]", self.lines("binary", 0)[0])

    def test_cursor_marks_the_highlighted_row_only(self):
        rows = [line for line in self.lines("binary", 2) if ">" in line]
        self.assertEqual(len(rows), 1)
        self.assertIn("unsigned", rows[0])

    def test_active_format_is_marked_independently_of_the_cursor(self):
        marked = [line for line in self.lines("hex", 0) if "*" in line]
        self.assertEqual(len(marked), 1)
        self.assertIn("hexadecimal", marked[0])

    def test_menu_states_its_own_controls(self):
        footer = " ".join(self.lines("binary", 0))
        self.assertIn("Enter", footer)
        self.assertIn("Esc", footer)

    def test_menu_uses_ascii_only_glyphs_when_asked(self):
        for line in self.lines("binary", 1, ascii_only=True):
            self.assertTrue(line.isascii(), line)

    def test_starting_index_is_the_active_format(self):
        self.assertEqual(vcdtui.value_format_index("unsigned"), 2)
        self.assertEqual(vcdtui.value_format_index("binary"), 0)

    def test_unknown_active_format_starts_at_the_first_entry(self):
        self.assertEqual(vcdtui.value_format_index("nonsense"), 0)


class HelpTests(unittest.TestCase):
    def test_help_documents_the_menu_keys(self):
        text = "\n".join(vcdtui._help_lines(ascii_only=True))
        self.assertRegex(text, r"v\s.*value format")
        self.assertIn("Enter", text)


if __name__ == "__main__":
    unittest.main()
