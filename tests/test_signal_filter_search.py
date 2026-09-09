import unittest

import vcdtui


class SignalFilterSearchTests(unittest.TestCase):
    def setUp(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$scope module cpu $end
$var wire 1 a clk $end
$var wire 1 b reset $end
$upscope $end
$var wire 4 c count [3:0] $end
$upscope $end
$enddefinitions $end
#0
0a
0b
b0000 c
"""
        self.vcd = vcdtui.parse_vcd_text(text)
        self.state = vcdtui.TUIState(
            cursor=0,
            view_start=0,
            view_end=10,
            selected=[True] * len(self.vcd.signals),
            expanded_scopes=vcdtui.all_scope_paths(self.vcd.signals),
            expanded_signals={2},
            shown_bits={(2, 1)},
        )

    def test_filter_keeps_matching_scope_ancestors(self):
        items = vcdtui.filtered_tree_items(
            self.vcd.signals,
            self.state.expanded_scopes,
            self.state.expanded_signals,
            "clk",
        )
        self.assertEqual([item.label for item in items], ["top", "cpu", "clk"])

    def test_filter_does_not_change_selection_and_matches_bits(self):
        rows = vcdtui.visible_wave_rows(self.vcd.signals, self.state, r"count\[2\]")
        self.assertEqual([row.signal.display_reference for row in rows], ["count[2]"])
        self.assertEqual([row.bit_position for row in rows], [1])
        self.assertEqual(self.state.selected, [True] * len(self.vcd.signals))

    def test_invalid_pattern_is_reported_and_leaves_items_visible(self):
        compiled, error = vcdtui.compile_signal_pattern("[")
        self.assertIsNone(compiled)
        self.assertTrue(error)
        self.assertEqual(
            len(vcdtui.filtered_tree_items(
                self.vcd.signals, self.state.expanded_scopes,
                self.state.expanded_signals, "["
            )),
            len(vcdtui.build_tree_items(
                self.vcd.signals, self.state.expanded_scopes,
                self.state.expanded_signals
            )),
        )

    def test_search_advances_focus_and_wraps_without_changing_selection(self):
        self.state.search_pattern = "t"
        first = vcdtui._search_signal(self.vcd.signals, self.state, forward=True)
        second = vcdtui._search_signal(self.vcd.signals, self.state, forward=True)
        self.assertEqual(first.reference, "reset")
        self.assertEqual(second.reference, "count")
        self.assertEqual(self.state.selected, [True] * len(self.vcd.signals))


if __name__ == "__main__":
    unittest.main()
