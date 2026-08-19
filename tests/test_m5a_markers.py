import unittest

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 4 $ count [3:0] $end
$var wire 1 % stop $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0010 $
0%
$end
#5
1!
#10
0!
b0001 $
#15
1!
#20
0!
b0000 $
1%
"""


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.signals = vcdtui.select_signals(self.vcd, "clk,count,stop")

    def test_marker_values_use_post_change_value_at_tick(self):
        self.assertEqual(vcdtui.marker_values(self.signals, 20), ["0", "0000", "1"])
        self.assertEqual(vcdtui.marker_values(self.signals, 10), ["0", "0001", "0"])

    def test_delta_is_signed_b_minus_a(self):
        self.assertEqual(vcdtui.marker_delta_ticks(10, 20), 10)
        self.assertEqual(vcdtui.marker_delta_ticks(20, 10), -10)
        self.assertEqual(vcdtui.marker_delta_ticks(10, 10), 0)
        self.assertIsNone(vcdtui.marker_delta_ticks(10, None))

    def test_marker_table_contains_values_and_exact_delta(self):
        lines = vcdtui.marker_table_lines(
            self.vcd,
            self.signals,
            10,
            20,
            120,
            ascii_only=True,
        )
        text = "\n".join(lines)
        self.assertIn("marker", lines[0])
        self.assertIn("count[3:0]", lines[0])
        self.assertIn("0001", lines[1])
        self.assertIn("0000", lines[2])
        self.assertIn("delta", lines[3])
        self.assertIn("10ns", lines[3])

    def test_marker_table_tracks_current_signal_selection(self):
        lines = vcdtui.marker_table_lines(
            self.vcd,
            [self.signals[0], self.signals[2]],
            10,
            20,
            120,
            ascii_only=False,
        )
        header = lines[0]
        self.assertIn("clk", header)
        self.assertIn("stop", header)
        self.assertNotIn("count", header)

    def test_marker_table_is_width_bounded(self):
        lines = vcdtui.marker_table_lines(
            self.vcd,
            self.signals,
            10,
            20,
            38,
            ascii_only=True,
        )
        self.assertTrue(all(len(line) <= 38 for line in lines))


if __name__ == "__main__":
    unittest.main()
