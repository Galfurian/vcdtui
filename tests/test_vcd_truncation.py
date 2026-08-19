"""Truncated traces.

A simulation killed part way through leaves a VCD whose header is intact and
whose value changes simply stop. Refusing to open it throws away everything
that was recorded up to that point, which is usually the interesting part.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import vcdtui


HEADER = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$var reg 4 " count $end
$upscope $end
$enddefinitions $end
"""


class TruncatedValueChangeTests(unittest.TestCase):
    def parse(self, body):
        return vcdtui.parse_vcd_text(HEADER + body)

    def test_trace_cut_mid_vector_keeps_what_came_before(self):
        vcd = self.parse("#0\n0!\nb0 \"\n#5\n1!\nb1")
        self.assertEqual(vcd.last_time, 5)
        self.assertEqual(
            [(c.time, c.value) for c in vcd.streams["!"].changes], [(0, "0"), (5, "1")]
        )
        self.assertEqual([(c.time, c.value) for c in vcd.streams['"'].changes], [(0, "0000")])

    def test_trace_cut_inside_a_dump_block_keeps_what_came_before(self):
        vcd = self.parse("#0\n$dumpvars\n0!\nb1010 \"\n")
        self.assertEqual([(c.time, c.value) for c in vcd.streams["!"].changes], [(0, "0")])
        self.assertEqual([(c.time, c.value) for c in vcd.streams['"'].changes], [(0, "1010")])

    def test_trace_cut_mid_scalar_token_keeps_what_came_before(self):
        vcd = self.parse("#0\n0!\n#5\n1")
        self.assertEqual([(c.time, c.value) for c in vcd.streams["!"].changes], [(0, "0")])

    def test_truncation_is_reported_as_a_warning(self):
        vcd = self.parse("#0\n0!\n#5\n1!\nb1")
        self.assertEqual(len(vcd.warnings), 1)
        self.assertIn("truncated", vcd.warnings[0])
        self.assertIn("line 11", vcd.warnings[0])

    def test_a_complete_trace_warns_about_nothing(self):
        self.assertEqual(self.parse("#0\n0!\n#5\n1!\n").warnings, [])

    def test_truncation_after_the_header_still_yields_the_signals(self):
        vcd = self.parse("")
        self.assertEqual([s.full_name for s in vcd.signals], ["top.clk", "top.count"])
        self.assertEqual(vcd.warnings, [])


class TruncatedHeaderTests(unittest.TestCase):
    def test_a_header_cut_before_enddefinitions_is_still_fatal(self):
        # Nothing usable can be recovered: the identifier map is incomplete.
        text = "$timescale 1 ns $end\n$scope module top $end\n$var reg 1 ! clk $end\n"
        with self.assertRaisesRegex(vcdtui.VCDParseError, "missing \\$enddefinitions"):
            vcdtui.parse_vcd_text(text)

    def test_a_directive_cut_mid_way_is_still_fatal(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "end of file"):
            vcdtui.parse_vcd_text("$timescale 1 ns $end\n$scope module top\n")


class WarningOutputTests(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcdtui.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_warnings_go_to_stderr_and_do_not_change_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cut.vcd"
            path.write_text(HEADER + "#0\n0!\n#5\n1!\nb1", encoding="utf-8")
            code, out, err = self.run_cli([str(path), "--list"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "top.clk\ntop.count\n")
        self.assertIn("vcdtui: warning:", err)
        self.assertIn("truncated", err)

    def test_a_complete_trace_produces_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whole.vcd"
            path.write_text(HEADER + "#0\n0!\n", encoding="utf-8")
            code, _, err = self.run_cli([str(path), "--list"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
