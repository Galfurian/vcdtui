import unittest

import vcdtui


SAMPLE = """\
$timescale 10 ps $end
$scope module top $end
$var wire 1 ! sig $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
$end
#5
1!
#10
0!
#12
x!
#15
1!
#18
0!
#20
1!
#25
0!
"""


class FakeCurses:
    KEY_HOME = 1001
    KEY_END = 1002

    def __init__(self, names):
        self.names = names

    def keyname(self, key):
        return self.names[key]


class NavigationRulerTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.stream = self.vcd.signals[0].stream

    def test_any_edge_uses_only_clean_binary_transitions(self):
        self.assertEqual(vcdtui.edge_times(self.stream, "any"), [5, 10, 18, 20, 25])
        self.assertEqual(vcdtui.edge_times(self.stream, "rising"), [5, 20])
        self.assertEqual(vcdtui.edge_times(self.stream, "falling"), [10, 18, 25])

    def test_next_previous_any_edge(self):
        self.assertEqual(vcdtui.next_edge(self.stream, 10, "any", forward=True), 18)
        self.assertEqual(vcdtui.next_edge(self.stream, 18, "any", forward=False), 10)
        self.assertIsNone(vcdtui.next_edge(self.stream, 25, "any", forward=True))

    def test_nice_step_follows_125_decades(self):
        self.assertEqual(vcdtui.nice_timeline_step(0, 100, 80), 20)
        self.assertEqual(vcdtui.nice_timeline_step(0, 1000, 80), 200)
        self.assertEqual(vcdtui.nice_timeline_step(0, 9, 80), 2)
        self.assertEqual(vcdtui.nice_timeline_step(7, 7, 80), 1)

    def test_timeline_ruler_has_stable_width_and_exact_labels(self):
        labels, rule = vcdtui.render_timeline_ruler(
            self.vcd.timescale,
            0,
            100,
            61,
            ascii_only=True,
        )
        self.assertEqual(len(labels), 61)
        self.assertEqual(len(rule), 61)
        self.assertTrue(labels.startswith("0ps"))
        self.assertTrue(labels.rstrip().endswith("1ns"))
        self.assertIn("|", rule)
        self.assertIn(".", rule)

    def test_unicode_timeline_uses_unicode_rule(self):
        labels, rule = vcdtui.render_timeline_ruler(
            self.vcd.timescale,
            0,
            25,
            50,
            ascii_only=False,
        )
        self.assertEqual(len(labels), 50)
        self.assertEqual(len(rule), 50)
        self.assertIn("─", rule)
        self.assertIn("┼", rule)

    def test_ctrl_arrow_names_are_optional_aliases(self):
        fake = FakeCurses({1: b"kLFT5", 2: b"kRIT5", 3: b"KEY_LEFT"})
        self.assertIs(vcdtui._ctrl_horizontal_direction(fake, 1), False)
        self.assertIs(vcdtui._ctrl_horizontal_direction(fake, 2), True)
        self.assertIsNone(vcdtui._ctrl_horizontal_direction(fake, 3))

    def test_home_end_and_legacy_aliases_map_to_range_boundaries(self):
        fake = FakeCurses({})
        self.assertEqual(vcdtui._range_boundary_for_key(fake, fake.KEY_HOME, 7, 42), 7)
        self.assertEqual(vcdtui._range_boundary_for_key(fake, fake.KEY_END, 7, 42), 42)
        self.assertEqual(vcdtui._range_boundary_for_key(fake, ord("0"), 7, 42), 7)
        self.assertEqual(vcdtui._range_boundary_for_key(fake, ord("$"), 7, 42), 42)
        self.assertIsNone(vcdtui._range_boundary_for_key(fake, ord("x"), 7, 42))


if __name__ == "__main__":
    unittest.main()
