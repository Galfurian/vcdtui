"""Space is the only toggle, and on a scope it toggles the whole group."""

import unittest

import vcdtui


# Two instances of the same module, so every leaf name is ambiguous: the shape
# that makes group selection worth having.
SAMPLE = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 1 ! clk $end
$var reg 1 " start $end
$scope module dut4 $end
$var reg 1 # clk $end
$var reg 4 $ value [3:0] $end
$upscope $end
$scope module dut8 $end
$var reg 1 % clk $end
$var reg 8 & value [7:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
0#
b0 $
0%
b0 &
"""


class ScopeMembershipTests(unittest.TestCase):
    def setUp(self):
        self.signals = vcdtui.parse_vcd_text(SAMPLE).signals

    def names(self, path):
        return [
            self.signals[index].full_name
            for index in vcdtui.signal_indexes_in_scope(self.signals, path)
        ]

    def test_a_leaf_scope_holds_its_own_signals(self):
        self.assertEqual(self.names(("tb", "dut4")), ["tb.dut4.clk", "tb.dut4.value"])

    def test_a_parent_scope_holds_everything_below_it(self):
        self.assertEqual(
            self.names(("tb",)),
            [
                "tb.clk",
                "tb.start",
                "tb.dut4.clk",
                "tb.dut4.value",
                "tb.dut8.clk",
                "tb.dut8.value",
            ],
        )

    def test_an_unknown_scope_holds_nothing(self):
        self.assertEqual(self.names(("nope",)), [])

    def test_a_scope_is_not_matched_by_a_name_prefix(self):
        # "dut" must not pick up "dut4" and "dut8".
        self.assertEqual(self.names(("tb", "dut")), [])


class ScopeToggleTests(unittest.TestCase):
    def test_a_partly_shown_group_becomes_fully_shown(self):
        selected = [True, False, False, True]
        self.assertEqual(
            vcdtui.toggle_scope_selection(selected, [1, 2]), [True, True, True, True]
        )

    def test_a_fully_shown_group_becomes_hidden(self):
        selected = [False, True, True, False]
        self.assertEqual(
            vcdtui.toggle_scope_selection(selected, [1, 2]), [False, False, False, False]
        )

    def test_signals_outside_the_group_are_untouched(self):
        selected = [True, False, False, True]
        self.assertEqual(vcdtui.toggle_scope_selection(selected, [1]), [True, True, False, True])

    def test_an_empty_group_changes_nothing(self):
        self.assertEqual(vcdtui.toggle_scope_selection([True, False], []), [True, False])

    def test_the_input_list_is_not_mutated(self):
        selected = [True, True]
        vcdtui.toggle_scope_selection(selected, [0, 1])
        self.assertEqual(selected, [True, True])


class HelpTests(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(vcdtui._help_lines(ascii_only=True))

    def test_enter_is_documented_as_expand_only(self):
        line = next(l for l in self.text.splitlines() if l.strip().startswith("Enter"))
        self.assertNotIn("toggle", line)
        self.assertIn("scope", line)

    def test_space_is_documented_as_the_toggle_for_signals_and_scopes(self):
        line = next(l for l in self.text.splitlines() if l.strip().startswith("Space"))
        self.assertIn("scope", line)


if __name__ == "__main__":
    unittest.main()
