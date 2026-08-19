import unittest

import vcdtui


class FakeCurses:
    KEY_F1 = 1001


class UIHelpPolishTests(unittest.TestCase):
    def test_f1_and_question_mark_open_help_but_h_does_not(self):
        self.assertTrue(vcdtui._is_help_key(FakeCurses, FakeCurses.KEY_F1))
        self.assertTrue(vcdtui._is_help_key(FakeCurses, ord("?")))
        self.assertFalse(vcdtui._is_help_key(FakeCurses, ord("h")))

    def test_help_contains_full_control_groups(self):
        text = "\n".join(vcdtui._help_lines(ascii_only=False))
        for expected in (
            "Signals",
            "Time & view",
            "Inspect",
            "Ctrl+←/→",
            "Home / End",
            "n/N  e/E  r/R  f/F",
            "m / M",
            "F1 / ?",
        ):
            self.assertIn(expected, text)

    def test_shortcut_bar_is_curated_and_width_bounded(self):
        wide = vcdtui.shortcut_bar(120, ascii_only=False)
        self.assertIn("Tab pane", wide)
        self.assertIn("F1/? help", wide)
        self.assertIn("q quit", wide)
        for width in (80, 60, 40, 12, 1):
            self.assertLessEqual(len(vcdtui.shortcut_bar(width, ascii_only=False)), width)

    def test_ascii_shortcut_bar_avoids_unicode_arrows(self):
        text = vcdtui.shortcut_bar(120, ascii_only=True)
        self.assertNotIn("←", text)
        self.assertNotIn("→", text)
        self.assertIn("<- -> cursor", text)

    def test_help_panel_is_centered_and_clamped(self):
        self.assertEqual(
            vcdtui._centered_panel_geometry(30, 100, 60, 20),
            (4, 18, 22, 64),
        )
        top, left, height, width = vcdtui._centered_panel_geometry(10, 20, 60, 20)
        self.assertEqual((top, left), (0, 0))
        self.assertEqual((height, width), (10, 20))


if __name__ == "__main__":
    unittest.main()
