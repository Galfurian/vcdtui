"""$var reference handling: bit ranges, escaped identifiers, reopened scopes.

Icarus Verilog 12.0 writes the declared bit range as a separate token:

    $var reg 8 " count [7:0] $end
    $var reg 3 $ \\mem[0] [2:0] $end
    $var reg 1 # \\escaped$name $end

Folding that range into the reference produced names containing a space, such
as "top.count [7:0]", which no exact selector could ever match.
"""

import unittest

import vcdtui


TEXT = """\
$timescale 1 ns $end
$scope module top $end
$var wire 4 ! hi [3:0] $end
$var reg 8 " count [7:0] $end
$var reg 1 # \\escaped$name $end
$var wire 1 ' bit_of [3] $end
$var wire 1 ( plain $end
$upscope $end
$scope module top $end
$var reg 3 $ \\mem[0] [2:0] $end
$upscope $end
$enddefinitions $end
#0
b0 !
b0 "
0#
0'
0(
b0 $
"""


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(TEXT)
        self.by_ref = {signal.reference: signal for signal in self.vcd.signals}

    def test_full_names_exclude_the_declared_bit_range(self):
        self.assertEqual(
            [signal.full_name for signal in self.vcd.signals],
            [
                "top.hi",
                "top.count",
                "top.escaped$name",
                "top.bit_of",
                "top.plain",
                "top.mem[0]",
            ],
        )

    def test_bit_range_is_kept_separately(self):
        self.assertEqual(self.by_ref["count"].bit_range, "[7:0]")
        self.assertEqual(self.by_ref["bit_of"].bit_range, "[3]")
        self.assertEqual(self.by_ref["plain"].bit_range, "")
        self.assertEqual(self.by_ref["mem[0]"].bit_range, "[2:0]")

    def test_display_name_joins_name_and_range_without_a_space(self):
        self.assertEqual(self.by_ref["count"].display_name, "top.count[7:0]")
        self.assertEqual(self.by_ref["plain"].display_name, "top.plain")

    def test_escaped_identifier_loses_only_its_leading_backslash(self):
        self.assertEqual(self.by_ref["escaped$name"].full_name, "top.escaped$name")
        self.assertEqual(self.by_ref["mem[0]"].full_name, "top.mem[0]")

    def test_reopened_scope_does_not_nest(self):
        self.assertEqual(self.by_ref["mem[0]"].full_name, "top.mem[0]")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(TEXT)

    def select(self, selectors):
        return [s.full_name for s in vcdtui.select_signals(self.vcd, selectors)]

    def test_bare_name_selects_exactly_one_signal(self):
        self.assertEqual(self.select("count"), ["top.count"])

    def test_bare_name_does_not_fall_back_to_substring_matching(self):
        # "hi" used to miss its exact target ("hi [3:0]") and match nothing
        # useful; a failed exact match silently widened to every substring hit.
        self.assertEqual(self.select("hi"), ["top.hi"])

    def test_display_name_is_accepted_as_a_selector(self):
        self.assertEqual(self.select("top.count[7:0]"), ["top.count"])

    def test_escaped_name_is_selectable_without_the_backslash(self):
        self.assertEqual(self.select("escaped$name"), ["top.escaped$name"])


class DumpTests(unittest.TestCase):
    def test_dump_header_shows_the_declared_range(self):
        vcd = vcdtui.parse_vcd_text(TEXT)
        signals = vcdtui.select_signals(vcd, "count,plain")
        rendered = vcdtui.render_dump(vcd, signals, 0, 0, ascii_only=True, color=False)
        self.assertIn("top.count[7:0]", rendered)
        self.assertIn("top.plain", rendered)


class MalformedReferenceTests(unittest.TestCase):
    def test_var_without_a_reference_is_rejected(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! $end
$upscope $end
$enddefinitions $end
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "invalid \\$var"):
            vcdtui.parse_vcd_text(text)

    def test_reference_with_unexpected_trailing_tokens_is_rejected(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var wire 4 ! bus [3:0] junk $end
$upscope $end
$enddefinitions $end
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "\\$var"):
            vcdtui.parse_vcd_text(text)


if __name__ == "__main__":
    unittest.main()
