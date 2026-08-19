"""Select-all toggle, exercised through a pure helper.

Qualification never has to simulate terminal keystrokes.
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


class ToggleAllSelectionTests(unittest.TestCase):
    def test_partial_selection_becomes_all_shown(self):
        self.assertEqual(vcdtui.toggle_all_selection([True, False, False]), [True] * 3)

    def test_nothing_shown_becomes_all_shown(self):
        self.assertEqual(vcdtui.toggle_all_selection([False, False]), [True, True])

    def test_all_shown_becomes_nothing_shown(self):
        self.assertEqual(vcdtui.toggle_all_selection([True, True]), [False, False])

    def test_pressing_twice_returns_to_all_shown(self):
        once = vcdtui.toggle_all_selection([True, True])
        self.assertEqual(vcdtui.toggle_all_selection(once), [True, True])

    def test_empty_selection_is_handled(self):
        self.assertEqual(vcdtui.toggle_all_selection([]), [])


class HelpTests(unittest.TestCase):
    def test_help_documents_the_select_all_toggle(self):
        text = "\n".join(vcdtui._help_lines(ascii_only=True))
        self.assertIn("Ctrl+A", text)


if __name__ == "__main__":
    unittest.main()
