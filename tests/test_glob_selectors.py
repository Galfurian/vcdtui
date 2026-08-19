"""Glob selectors, following the shell convention with "." as the separator.

``*`` stays inside one hierarchy level and ``**`` crosses levels, as in bash
globstar and gitignore. Keeping the two distinct is the whole point: a pattern
that floated to any depth on its own would make ``**`` meaningless.
"""

import unittest

import vcdtui

from tests.test_scope_view import SAMPLE


class GlobMatchTests(unittest.TestCase):
    def matches(self, name, pattern):
        return vcdtui._glob_matches(name, pattern)

    def test_a_star_stays_inside_one_level(self):
        self.assertTrue(self.matches("tb.clk", "tb.*"))
        self.assertFalse(self.matches("tb.dut.clk", "tb.*"))

    def test_a_double_star_crosses_levels(self):
        self.assertTrue(self.matches("tb.clk", "tb.**"))
        self.assertTrue(self.matches("tb.dut.alu.carry", "tb.**"))

    def test_a_double_star_in_the_middle_spans_zero_or_more_scopes(self):
        self.assertTrue(self.matches("tb.clk", "tb.**.clk"))
        self.assertTrue(self.matches("tb.dut.alu.clk", "tb.**.clk"))
        self.assertFalse(self.matches("tb.dut.alu.carry", "tb.**.clk"))

    def test_a_question_mark_matches_one_character_inside_a_level(self):
        self.assertTrue(self.matches("tb.dut4.value", "tb.dut?.value"))
        self.assertFalse(self.matches("tb.dut42.value", "tb.dut?.value"))
        self.assertFalse(self.matches("tb.dut.4.value", "tb.dut?.value"))

    def test_a_pattern_with_a_separator_is_anchored_at_the_root(self):
        # As in gitignore: once a pattern names a path, it names it from the top.
        self.assertFalse(self.matches("tb.dut4.value", "dut4.value"))
        self.assertTrue(self.matches("tb.dut4.value", "**.dut4.value"))

    def test_a_pattern_without_a_separator_matches_a_leaf_at_any_depth(self):
        self.assertTrue(self.matches("tb.dut.alu.carry", "car*"))
        self.assertTrue(self.matches("carry", "car*"))
        self.assertFalse(self.matches("tb.carry.flag", "car*"))

    def test_brackets_are_literal(self):
        # Only "*" and "?" are special, so a declared bit range can be typed out.
        self.assertTrue(self.matches("tb.count[3:0]", "tb.count[3:0]"))
        self.assertTrue(self.matches("tb.count[3:0]", "tb.count*"))
        self.assertFalse(self.matches("tb.count3", "tb.count[3:0]"))

    def test_consecutive_double_stars_collapse(self):
        # Each "**" compiles to a repeated group, so several in a row nest
        # quantifiers and a pattern that fails to match backtracks
        # exponentially: 10 of them against 20 scopes took seconds. They all
        # mean the same thing, so only one survives.
        self.assertEqual(
            vcdtui._glob_regex("a.**.**.**.z").pattern,
            vcdtui._glob_regex("a.**.z").pattern,
        )
        self.assertTrue(self.matches("a.b.c.z", "a.**.**.z"))
        self.assertFalse(self.matches("a.b.c.y", "a.**.**.z"))

    def test_matching_is_case_insensitive_like_every_other_selector(self):
        self.assertTrue(self.matches("tb.CLK", "tb.c*"))


class GlobSelectionTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def select(self, selectors, warnings=None):
        chosen = vcdtui.select_signals(self.vcd, selectors, warnings=warnings)
        return [signal.full_name for signal in chosen]

    def test_a_star_selects_the_signals_directly_in_a_scope(self):
        self.assertEqual(
            self.select("tb_counter.*"),
            ["tb_counter.clk", "tb_counter.start", "tb_counter.in4"],
        )

    def test_a_double_star_selects_everything_below_a_scope(self):
        self.assertEqual(len(self.select("tb_counter.**")), 9)

    def test_a_glob_reaches_a_leaf_at_any_depth(self):
        self.assertEqual(
            self.select("**.clk"),
            ["tb_counter.clk", "tb_counter.dut4.clk", "tb_counter.dut8.clk"],
        )

    def test_a_glob_can_pick_one_instance(self):
        self.assertEqual(
            self.select("**.dut?.value"),
            ["tb_counter.dut4.value", "tb_counter.dut8.value"],
        )

    def test_a_glob_matches_the_declared_bit_range(self):
        self.assertEqual(self.select("**.value[7:0]"), ["tb_counter.dut8.value"])

    def test_a_glob_that_matches_nothing_is_an_error(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "'tb_counter.z\\*' was not found"):
            self.select("tb_counter.z*")

    def test_a_glob_matching_many_signals_is_not_reported_as_ambiguous(self):
        # A glob asks for a set on purpose, so naming the paths back would be
        # noise. A bare leaf name is the ambiguous case, and still warns.
        warnings = []
        self.assertEqual(len(self.select("tb_counter.**", warnings=warnings)), 9)
        self.assertEqual(warnings, [])
        self.select("clk", warnings=warnings)
        self.assertEqual(len(warnings), 1)

    def test_an_anchored_glob_is_preferred_over_a_floating_one(self):
        # "*.clk" names one scope then clk, counted from the root, which is
        # tb_counter.clk. The deeper clks need "**.clk" and say so.
        self.assertEqual(self.select("*.clk"), ["tb_counter.clk"])

    def test_a_glob_that_matches_nothing_at_the_root_floats(self):
        # Nothing is called "dut4" at the top level, so the pattern is retried
        # at every scope boundary, exactly as a plain path selector is.
        self.assertEqual(
            self.select("dut4.*"),
            ["tb_counter.dut4.clk", "tb_counter.dut4.value"],
        )

    def test_a_plain_selector_is_still_resolved_as_a_path(self):
        self.assertEqual(self.select("dut4.clk"), ["tb_counter.dut4.clk"])

    def test_globs_combine_with_plain_selectors(self):
        self.assertEqual(
            self.select("dut4.*,start"),
            ["tb_counter.start", "tb_counter.dut4.clk", "tb_counter.dut4.value"],
        )


class ScopedGlobTests(unittest.TestCase):
    def test_a_glob_is_anchored_at_the_scope_root(self):
        view = vcdtui.scoped_view(vcdtui.parse_vcd_text(SAMPLE), "tb_counter")
        chosen = vcdtui.select_signals(view, "dut?.value")
        self.assertEqual([s.full_name for s in chosen], ["dut4.value", "dut8.value"])


if __name__ == "__main__":
    unittest.main()
