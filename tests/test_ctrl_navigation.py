"""Ctrl+Left/Right step across edges for every kind of signal.

Scalars step across clean binary edges, vectors across value changes, and
real/string tracks report that they have nothing to step across. When no step
remains, the cursor is sent to the matching end of the active range, so the
first edge and the range start are both reachable.
"""

import unittest

import vcdtui

SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 4 $ bus [3:0] $end
$var real 1 % level $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0000 $
r1.5 %
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
#25
b0010 $
r2.0 %
"""


class CtrlNavigationTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.clk = next(s for s in self.vcd.signals if s.reference == "clk")
        self.bus = next(s for s in self.vcd.signals if s.reference == "bus")
        self.level = next(s for s in self.vcd.signals if s.reference == "level")
        self.timescale = self.vcd.timescale

    def target(self, signal, cursor, *, forward, start=0, end=25):
        return vcdtui.ctrl_navigation_target(
            signal, cursor, start, end, self.timescale, forward=forward
        )

    def test_a_scalar_steps_between_clean_binary_edges(self):
        tick, status = self.target(self.clk, 0, forward=True)
        self.assertEqual(tick, 5)
        self.assertIn("binary edge", status)
        tick, _ = self.target(self.clk, 20, forward=False)
        self.assertEqual(tick, 15)

    def test_a_vector_steps_between_value_changes(self):
        tick, status = self.target(self.bus, 0, forward=True)
        self.assertEqual(tick, 10)
        self.assertIn("value change", status)
        tick, _ = self.target(self.bus, 25, forward=False)
        self.assertEqual(tick, 10)

    def test_a_vector_does_not_step_across_edges(self):
        # The bus has no binary edges; its steps are its changes.
        self.assertEqual(vcdtui.edge_times(self.bus.stream, "any"), [])

    def test_real_signals_report_nothing_to_step_across(self):
        tick, status = self.target(self.level, 0, forward=True)
        self.assertIsNone(tick)
        self.assertIn("no edges to step across", status)

    def test_no_previous_edge_moves_to_the_range_start(self):
        # Standing on the first rising edge, Ctrl+Left has no earlier edge; the
        # cursor used to refuse to move at all.
        tick, status = self.target(self.clk, 5, forward=False)
        self.assertEqual(tick, 0)
        self.assertIn("moved to range start", status)

    def test_no_next_edge_moves_to_the_range_end(self):
        tick, status = self.target(self.clk, 20, forward=True)
        self.assertEqual(tick, 25)
        self.assertIn("moved to range end", status)

    def test_at_the_boundary_there_is_nothing_left_to_do(self):
        tick, status = self.target(self.clk, 0, forward=False)
        self.assertIsNone(tick)
        self.assertIn("no previous binary edge", status)
        tick, status = self.target(self.clk, 25, forward=True)
        self.assertIsNone(tick)
        self.assertIn("no next binary edge", status)

    def test_the_fallback_respects_the_active_range(self):
        tick, status = self.target(self.clk, 5, forward=False, start=3, end=20)
        self.assertEqual(tick, 3)
        tick, status = self.target(self.clk, 15, forward=True, start=3, end=20)
        self.assertEqual(tick, 20)

    def test_a_vector_also_falls_back_to_the_boundaries(self):
        # Past its last change there is nothing left to step to, so the cursor
        # is sent to the range end.
        tick, status = self.target(self.bus, 25, forward=True, end=30)
        self.assertEqual(tick, 30)
        self.assertIn("moved to range end", status)
        tick, status = self.target(self.bus, 25, forward=True)
        self.assertIsNone(tick)
        self.assertIn("no next value change", status)

    def test_a_vector_without_an_earlier_change_falls_back_to_the_start(self):
        stream = vcdtui.ValueStream(
            "$",
            4,
            "bit",
            [vcdtui.Change(10, "0001"), vcdtui.Change(25, "0010")],
        )
        signal = vcdtui.Signal("t", "t", 4, "wire", stream)
        tick, status = vcdtui.ctrl_navigation_target(
            signal, 10, 0, 25, self.timescale, forward=False
        )
        self.assertEqual(tick, 0)
        self.assertIn("moved to range start", status)

    def test_an_expanded_bit_steps_like_a_scalar(self):
        # The least significant bit of the bus rises at 10 and falls at 25.
        bit = vcdtui.build_bit_signal(self.bus, 3)
        tick, status = vcdtui.ctrl_navigation_target(
            bit, 0, 0, 25, self.timescale, forward=True
        )
        self.assertEqual(tick, 10)
        self.assertIn("binary edge", status)


if __name__ == "__main__":
    unittest.main()
