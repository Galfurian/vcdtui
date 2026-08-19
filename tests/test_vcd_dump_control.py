"""Regression tests for the value-change section: dump control and comments.

The reference input is the VCD emitted by Icarus Verilog 12.0, the qualified
simulation baseline. Icarus writes ``$comment`` and ``$dumpall`` immediately
after ``$enddefinitions``, before the first timestamp.
"""

import unittest

import vcdtui


ICARUS_PREAMBLE = """\
$date
	Wed Aug 19 19:25:57 2026
$end
$version
	Icarus Verilog
$end
$timescale
	1s
$end
$scope module top $end
$var wire 1 " w $end
$var reg 1 $ clk $end
$var reg 8 % count $end
$scope module u_sub $end
$var parameter 32 ) WIDTH $end
$upscope $end
$upscope $end
$enddefinitions $end
$comment Show the parameter values. $end
$dumpall
b100 )
$end
#0
$dumpvars
b0 %
0$
0"
$end
#5
1$
#10
1"
b10100101 %
"""


class IcarusPreambleTests(unittest.TestCase):
    def test_icarus_12_preamble_parses(self):
        vcd = vcdtui.parse_vcd_text(ICARUS_PREAMBLE)
        self.assertEqual(
            [signal.full_name for signal in vcd.signals],
            ["top.w", "top.clk", "top.count", "top.u_sub.WIDTH"],
        )
        self.assertEqual(vcd.last_time, 10)

    def test_dumpall_before_first_timestamp_records_values(self):
        vcd = vcdtui.parse_vcd_text(ICARUS_PREAMBLE)
        width = vcd.streams[")"]
        self.assertEqual(
            [(change.time, change.value) for change in width.changes],
            [(0, "00000000000000000000000000000100")],
        )

    def test_transitions_after_the_preamble(self):
        vcd = vcdtui.parse_vcd_text(ICARUS_PREAMBLE)
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["$"].changes],
            [(0, "0"), (5, "1")],
        )
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["%"].changes],
            [(0, "00000000"), (10, "10100101")],
        )


class DumpControlTests(unittest.TestCase):
    HEADER = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$var reg 4 " q $end
$upscope $end
$enddefinitions $end
"""

    def parse(self, body: str) -> vcdtui.VCDFile:
        return vcdtui.parse_vcd_text(self.HEADER + body)

    def test_dumpoff_and_dumpon_blocks_are_recorded(self):
        vcd = self.parse(
            """\
#0
$dumpvars
0!
b0 "
$end
#10
$dumpoff
x!
bx "
$end
#20
$dumpon
1!
b1010 "
$end
#30
0!
"""
        )
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["!"].changes],
            [(0, "0"), (10, "x"), (20, "1"), (30, "0")],
        )
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams['"'].changes],
            [(0, "0000"), (10, "xxxx"), (20, "1010")],
        )

    def test_comment_between_value_changes_is_ignored(self):
        vcd = self.parse(
            """\
#0
0!
$comment checkpoint $end
#5
1!
"""
        )
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["!"].changes],
            [(0, "0"), (5, "1")],
        )

    def test_multiline_comment_between_value_changes_is_ignored(self):
        vcd = self.parse("#0\n0!\n$comment\n  0! is not a value change here\n$end\n#5\n1!\n")
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["!"].changes],
            [(0, "0"), (5, "1")],
        )

    def test_changes_may_follow_a_dump_block_at_the_same_timestamp(self):
        vcd = self.parse("#0\n$dumpon\n0!\n$end\n1!\n")
        self.assertEqual(
            [(change.time, change.value) for change in vcd.streams["!"].changes],
            [(0, "1")],
        )

    def test_timestamp_inside_dump_block_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"timestamp.*inside \$dumpvars"):
            self.parse("#0\n$dumpvars\n0!\n#5\n$end\n")

    def test_nested_dump_block_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"\$dumpall.*inside \$dumpvars"):
            self.parse("#0\n$dumpvars\n0!\n$dumpall\n$end\n$end\n")

    def test_unterminated_dump_block_is_truncation_not_corruption(self):
        # The block never closes because the writer stopped, so keep the values
        # it did contain and report it. See tests/test_vcd_truncation.py.
        vcd = self.parse("#0\n$dumpvars\n0!\n")
        self.assertEqual([c.value for c in vcd.streams["!"].changes], ["0"])
        self.assertIn("unterminated $dumpvars", vcd.warnings[0])

    def test_stray_end_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"\$end"):
            self.parse("#0\n0!\n$end\n")

    def test_unknown_value_change_directive_is_rejected(self):
        with self.assertRaisesRegex(
            vcdtui.VCDParseError, r"unsupported value-change directive \$nope"
        ):
            self.parse("#0\n$nope\n$end\n")


if __name__ == "__main__":
    unittest.main()
