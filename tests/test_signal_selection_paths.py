"""Selecting signals by path, and being told when a selector is ambiguous.

A testbench instantiating the same module twice has identically named leaves in
every scope, so a bare leaf name necessarily matches more than one signal.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module tb_counter $end
$var reg 1 ! clk $end
$var reg 1 " start $end
$var reg 4 * in4 [3:0] $end
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
b0 *
0#
b0 $
0%
b0 &
"""


class PathSelectionTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def select(self, selectors, warnings=None):
        chosen = vcdtui.select_signals(self.vcd, selectors, warnings=warnings)
        return [signal.full_name for signal in chosen]

    def test_full_path_selects_exactly_one_signal(self):
        self.assertEqual(self.select("tb_counter.dut4.clk"), ["tb_counter.dut4.clk"])

    def test_path_suffix_selects_exactly_one_signal(self):
        self.assertEqual(self.select("dut4.clk"), ["tb_counter.dut4.clk"])
        self.assertEqual(self.select("dut8.value"), ["tb_counter.dut8.value"])

    def test_a_path_selector_is_anchored_at_a_scope_boundary(self):
        # "ut4.clk" is a substring of the path but not a run of its components,
        # so it must not resolve as a path. It may still fall through to the
        # substring tier, which is a separate, weaker promise.
        self.assertTrue(vcdtui._matches_path("tb.dut4.clk", "tb.dut4.clk"))
        self.assertTrue(vcdtui._matches_path("tb.dut4.clk", "dut4.clk"))
        self.assertTrue(vcdtui._matches_path("tb.dut4.clk", "clk"))
        self.assertFalse(vcdtui._matches_path("tb.dut4.clk", "ut4.clk"))
        self.assertFalse(vcdtui._matches_path("tb.dut4.clk", "dut4"))
        self.assertFalse(vcdtui._matches_path("tb.dut4.clk", "lk"))

    def test_leaf_name_selects_it_in_every_scope(self):
        self.assertEqual(
            self.select("clk"),
            ["tb_counter.clk", "tb_counter.dut4.clk", "tb_counter.dut8.clk"],
        )

    def test_top_level_signal_is_selectable_by_its_bare_name(self):
        self.assertEqual(self.select("start"), ["tb_counter.start"])

    def test_display_name_with_its_bit_range_is_accepted(self):
        self.assertEqual(self.select("dut4.value[3:0]"), ["tb_counter.dut4.value"])

    def test_substring_is_still_a_last_resort(self):
        self.assertEqual(self.select("in"), ["tb_counter.in4"])

    def test_selection_keeps_declaration_order_and_deduplicates(self):
        self.assertEqual(
            self.select("clk,tb_counter.dut4.clk"),
            ["tb_counter.clk", "tb_counter.dut4.clk", "tb_counter.dut8.clk"],
        )

    def test_unknown_selector_is_an_error(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "'nope' was not found"):
            self.select("nope")


class AmbiguityWarningTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def warnings_for(self, selectors):
        warnings = []
        vcdtui.select_signals(self.vcd, selectors, warnings=warnings)
        return warnings

    def test_an_ambiguous_selector_lists_the_paths_it_matched(self):
        warnings = self.warnings_for("clk")
        self.assertEqual(len(warnings), 1)
        for name in ("tb_counter.clk", "tb_counter.dut4.clk", "tb_counter.dut8.clk"):
            self.assertIn(name, warnings[0])

    def test_an_unambiguous_selector_warns_about_nothing(self):
        self.assertEqual(self.warnings_for("dut4.clk"), [])
        self.assertEqual(self.warnings_for("start"), [])

    def test_selecting_everything_warns_about_nothing(self):
        self.assertEqual(self.warnings_for(None), [])

    def test_each_ambiguous_selector_is_reported_once(self):
        self.assertEqual(len(self.warnings_for("clk,value")), 2)


class CLIWarningTests(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcdtui.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_ambiguity_is_reported_on_stderr_without_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tb.vcd"
            path.write_text(SAMPLE, encoding="utf-8")
            code, out, err = self.run_cli(
                [str(path), "--signals", "clk", "--dump", "--ascii", "--no-color"]
            )
        self.assertEqual(code, 0)
        self.assertIn("tb_counter.dut8.clk", err)
        self.assertIn("vcdtui: warning:", err)
        self.assertIn("tb_counter.clk", out)


if __name__ == "__main__":
    unittest.main()
