"""Resolving selectors relative to one scope, and naming signals from it.

A testbench that instantiates the same module twice has to spell out an instance
path for every selector, which is unreadable in teaching material. ``--scope``
names the instance once and makes every other name relative to it.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import vcdtui


# tb_counter drives two differently sized copies of the same counter, and each
# copy contains an identically named inner scope. That is what makes bare leaf
# names ambiguous in the first place.
SAMPLE = """\
$timescale 1 ns $end
$scope module tb_counter $end
$var reg 1 ! clk $end
$var reg 1 " start $end
$var reg 4 * in4 [3:0] $end
$scope module dut4 $end
$var reg 1 # clk $end
$var reg 4 $ value [3:0] $end
$scope module regfile $end
$var reg 4 ( state [3:0] $end
$upscope $end
$upscope $end
$scope module dut8 $end
$var reg 1 % clk $end
$var reg 8 & value [7:0] $end
$scope module regfile $end
$var reg 8 ) state [7:0] $end
$upscope $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
b0 *
0#
b0 $
b0 (
0%
b0 &
b0 )
"""


class ScopePathTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def test_every_scope_is_listed_in_declaration_order(self):
        self.assertEqual(
            vcdtui.scope_paths(self.vcd),
            [
                "tb_counter",
                "tb_counter.dut4",
                "tb_counter.dut4.regfile",
                "tb_counter.dut8",
                "tb_counter.dut8.regfile",
            ],
        )

    def test_a_full_scope_path_resolves_to_itself(self):
        self.assertEqual(
            vcdtui.resolve_scope(self.vcd, "tb_counter.dut4"), "tb_counter.dut4"
        )

    def test_a_trailing_run_of_scopes_resolves(self):
        self.assertEqual(vcdtui.resolve_scope(self.vcd, "dut4"), "tb_counter.dut4")
        self.assertEqual(
            vcdtui.resolve_scope(self.vcd, "dut8.regfile"), "tb_counter.dut8.regfile"
        )

    def test_an_unknown_scope_is_an_error(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "scope 'nope' was not found"):
            vcdtui.resolve_scope(self.vcd, "nope")

    def test_a_signal_path_is_not_a_scope(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "was not found"):
            vcdtui.resolve_scope(self.vcd, "tb_counter.clk")

    def test_an_ambiguous_scope_is_an_error_that_names_the_candidates(self):
        with self.assertRaises(vcdtui.VCDTUIError) as caught:
            vcdtui.resolve_scope(self.vcd, "regfile")
        message = str(caught.exception)
        self.assertIn("tb_counter.dut4.regfile", message)
        self.assertIn("tb_counter.dut8.regfile", message)


class ScopedViewTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def names_under(self, scope):
        view = vcdtui.scoped_view(self.vcd, scope)
        return [signal.full_name for signal in view.signals]

    def test_names_are_relative_to_the_scope(self):
        self.assertEqual(
            self.names_under("tb_counter"),
            [
                "clk",
                "start",
                "in4",
                "dut4.clk",
                "dut4.value",
                "dut4.regfile.state",
                "dut8.clk",
                "dut8.value",
                "dut8.regfile.state",
            ],
        )

    def test_signals_outside_the_scope_are_dropped(self):
        self.assertEqual(self.names_under("dut4"), ["clk", "value", "regfile.state"])

    def test_leaf_names_and_bit_ranges_are_untouched(self):
        view = vcdtui.scoped_view(self.vcd, "dut4")
        value = view.signals[1]
        self.assertEqual(value.reference, "value")
        self.assertEqual(value.bit_range, "[3:0]")
        self.assertEqual(value.display_name, "value[3:0]")

    def test_the_view_shares_the_recorded_values(self):
        view = vcdtui.scoped_view(self.vcd, "dut4")
        self.assertIs(view.signals[0].stream, self.vcd.signals[3].stream)
        self.assertEqual(view.timescale.unit, self.vcd.timescale.unit)
        self.assertEqual(view.last_time, self.vcd.last_time)


class ScopedSelectionTests(unittest.TestCase):
    """The point of the feature: short selectors that mean one signal each."""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def test_a_leaf_name_in_the_scope_selects_only_that_signal(self):
        view = vcdtui.scoped_view(self.vcd, "tb_counter")
        warnings = []
        chosen = vcdtui.select_signals(view, "clk,start,in4", warnings=warnings)
        self.assertEqual(
            [signal.full_name for signal in chosen], ["clk", "start", "in4"]
        )
        self.assertEqual(warnings, [])

    def test_an_exact_name_is_preferred_over_a_trailing_run_match(self):
        # "clk" is both the name of a top-level signal and the trailing run of
        # two others. The exact name wins, so it is never widened.
        view = vcdtui.scoped_view(self.vcd, "tb_counter")
        self.assertEqual(
            [s.full_name for s in vcdtui.select_signals(view, "clk")], ["clk"]
        )

    def test_a_deeper_name_is_still_reachable_from_the_scope(self):
        view = vcdtui.scoped_view(self.vcd, "tb_counter")
        chosen = vcdtui.select_signals(view, "dut8.value")
        self.assertEqual([s.full_name for s in chosen], ["dut8.value"])

    def test_a_name_outside_the_scope_is_an_error(self):
        view = vcdtui.scoped_view(self.vcd, "dut4")
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "'dut8.value' was not found"):
            vcdtui.select_signals(view, "dut8.value")

    def test_without_a_scope_a_leaf_name_still_matches_every_copy(self):
        chosen = vcdtui.select_signals(self.vcd, "clk")
        self.assertEqual(
            [signal.full_name for signal in chosen],
            ["tb_counter.clk", "tb_counter.dut4.clk", "tb_counter.dut8.clk"],
        )


class ScopeCLITests(unittest.TestCase):
    def run_cli(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tb.vcd"
            path.write_text(SAMPLE, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = vcdtui.main([str(path), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_list_prints_names_relative_to_the_scope(self):
        code, out, _ = self.run_cli(["--scope", "dut4", "--list"])
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ["clk", "value", "regfile.state"])

    def test_list_without_a_scope_still_prints_full_paths(self):
        code, out, _ = self.run_cli(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("tb_counter.dut4.clk", out)

    def test_dump_headers_are_relative_to_the_scope(self):
        code, out, err = self.run_cli(
            [
                "--scope",
                "tb_counter",
                "-s",
                "clk,start,dut4.value",
                "--dump",
                "--ascii",
                "--no-color",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        header = next(line for line in out.splitlines() if line.startswith("tick"))
        self.assertIn("clk", header)
        self.assertIn("dut4.value[3:0]", header)
        self.assertNotIn("tb_counter", header)

    def test_an_unknown_scope_fails_with_a_clear_message(self):
        code, _, err = self.run_cli(["--scope", "nope", "--list"])
        self.assertEqual(code, 2)
        self.assertIn("scope 'nope' was not found", err)

    def test_find_searches_within_the_scope(self):
        code, out, _ = self.run_cli(["--scope", "dut8", "--find", "state"])
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ["regfile.state"])


if __name__ == "__main__":
    unittest.main()
