import unittest
import vcdtui

SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 4 $ bus [3:0] $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0000 $
$end
#5
1!
#10
0!
#15
x!
#20
1!
#25
0!
"""


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.clk = self.vcd.streams["!"]
        self.bus = self.vcd.streams["$"]

    def test_next_and_previous_transition_are_strict(self):
        self.assertEqual(vcdtui.next_transition(self.clk, 5, forward=True), 10)
        self.assertEqual(vcdtui.next_transition(self.clk, 5, forward=False), 0)
        self.assertIsNone(vcdtui.next_transition(self.clk, 25, forward=True))
        self.assertIsNone(vcdtui.next_transition(self.clk, 0, forward=False))

    def test_edges_only_count_clean_binary_transitions(self):
        self.assertEqual(vcdtui.edge_times(self.clk, "rising"), [5])
        self.assertEqual(vcdtui.edge_times(self.clk, "falling"), [10, 25])
        self.assertEqual(vcdtui.next_edge(self.clk, 0, "rising", forward=True), 5)
        self.assertEqual(vcdtui.next_edge(self.clk, 20, "falling", forward=True), 25)
        self.assertEqual(vcdtui.next_edge(self.clk, 25, "falling", forward=False), 10)
        self.assertEqual(vcdtui.edge_times(self.bus, "rising"), [])

    def test_pan_is_bounded_and_preserves_span(self):
        self.assertEqual(vcdtui.pan_window(20, 60, 0, 100, forward=True), (30, 70))
        self.assertEqual(vcdtui.pan_window(20, 60, 0, 100, forward=False), (10, 50))
        self.assertEqual(vcdtui.pan_window(0, 40, 0, 100, forward=False), (0, 40))
        self.assertEqual(vcdtui.pan_window(60, 100, 0, 100, forward=True), (60, 100))

    def test_zoom_centers_on_cursor_and_stays_bounded(self):
        self.assertEqual(vcdtui.zoom_window(0, 100, 50, 0, 100, zoom_in=True), (25, 75))
        self.assertEqual(vcdtui.zoom_window(25, 75, 50, 0, 100, zoom_in=False), (0, 100))
        self.assertEqual(vcdtui.zoom_window(0, 20, 0, 0, 100, zoom_in=True), (0, 10))

    def test_recenter_preserves_view_span(self):
        self.assertEqual(vcdtui.recenter_window(20, 40, 80, 0, 100), (70, 90))
        self.assertEqual(vcdtui.recenter_window(20, 40, 30, 0, 100), (20, 40))
        self.assertEqual(vcdtui.recenter_window(80, 100, 0, 0, 100), (0, 20))

    def test_selection_mask_preserves_signal_order(self):
        all_signals = self.vcd.signals
        selected = vcdtui.selected_signals(all_signals, [False, True])
        self.assertEqual([signal.reference for signal in selected], ["bus [3:0]"])
        mask = vcdtui._initial_selection(all_signals, [all_signals[0]])
        self.assertEqual(mask, [True, False])


if __name__ == "__main__":
    unittest.main()
