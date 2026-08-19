import unittest

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 4 $ count [3:0] $end
$upscope $end
$scope module aux $end
$var wire 1 % ready $end
$upscope $end
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
1%
#15
1!
#20
0!
b0000 $
"""


class UIPolishTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def test_tree_is_hierarchical_and_collapsible(self):
        expanded = vcdtui.all_scope_paths(self.vcd.signals)
        items = vcdtui.build_tree_items(self.vcd.signals, expanded)
        self.assertEqual([item.label for item in items[:3]], ["top", "dut", "clk"])
        collapsed = vcdtui.build_tree_items(self.vcd.signals, {("top",)})
        self.assertEqual([item.label for item in collapsed], ["top", "dut", "aux"])

    def test_scalar_track_draws_rising_and_falling_edges(self):
        clk = next(s for s in self.vcd.signals if s.reference == "clk")
        track = vcdtui.render_scalar_track(clk, 0, 20, 21, ascii_only=True)
        self.assertIn("/", track)
        self.assertIn("\\", track)

    def test_cursor_preserves_waveform_glyph(self):
        clk = next(s for s in self.vcd.signals if s.reference == "clk")
        track = vcdtui.render_scalar_track(clk, 0, 20, 21, ascii_only=True)
        edge = track.index("/")
        self.assertEqual(vcdtui.cursor_track_glyph(track, edge), "/")

    def test_bus_values_are_written_on_track(self):
        count = next(s for s in self.vcd.signals if s.reference.startswith("count"))
        track = vcdtui.render_bus_track(count, 0, 20, 60, ascii_only=True)
        self.assertIn("0010", track)
        self.assertIn("0001", track)

    def test_polished_track_keeps_requested_width(self):
        for signal in self.vcd.signals:
            self.assertEqual(
                len(vcdtui.render_waveform_track(signal, 0, 20, 37, ascii_only=False)),
                37,
            )


if __name__ == "__main__":
    unittest.main()
