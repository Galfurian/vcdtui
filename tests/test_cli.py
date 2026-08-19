import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import vcdtui


SAMPLE = """\
$date
  today
$end
$version test generator $end
$timescale 10 ps $end
$scope module top $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 4 $ count [3:0] $end
$var wire 1 ! clk_alias $end
$upscope $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0011 $
$end
#10
1!
#20
0!
b10 $
"""


class ParserTests(unittest.TestCase):
    def test_aliases_share_stream(self):
        vcd = vcdtui.parse_vcd_text(SAMPLE)
        clk = next(s for s in vcd.signals if s.reference == "clk")
        alias = next(s for s in vcd.signals if s.reference == "clk_alias")
        self.assertIs(clk.stream, alias.stream)
        self.assertEqual(clk.stream.identifier, "!")
        self.assertEqual([c.value for c in clk.stream.changes], ["0", "1", "0"])

    def test_nested_names_and_vector_normalization(self):
        vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.assertEqual(
            [s.full_name for s in vcd.signals],
            ["top.dut.clk", "top.dut.count [3:0]", "top.dut.clk_alias"],
        )
        count = vcd.streams["$"]
        self.assertEqual([c.value for c in count.changes], ["0011", "0010"])

    def test_exact_time_conversion(self):
        scale = vcdtui.TimeScale(10, "ps")
        self.assertEqual(scale.parse_ticks("1ns"), 100)
        self.assertEqual(scale.parse_ticks("42"), 42)
        with self.assertRaises(vcdtui.VCDTUIError):
            scale.parse_ticks("15ps")

    def test_incompatible_alias_width_is_error(self):
        text = SAMPLE.replace("$var wire 1 ! clk_alias $end", "$var wire 2 ! clk_alias $end")
        with self.assertRaisesRegex(vcdtui.VCDParseError, "incompatible widths"):
            vcdtui.parse_vcd_text(text)

    def test_real_value_conflicting_with_recorded_bits_is_error(self):
        text = SAMPLE + "r1.25 !\n"
        with self.assertRaisesRegex(vcdtui.VCDParseError, "real value used for"):
            vcdtui.parse_vcd_text(text)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sample.vcd"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = vcdtui.main([str(self.path), *args])
        return code, out.getvalue(), err.getvalue()

    def test_list(self):
        code, out, err = self.run_main("--list")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out.splitlines(),
            ["top.dut.clk", "top.dut.count [3:0]", "top.dut.clk_alias"],
        )

    def test_find_case_insensitive(self):
        code, out, err = self.run_main("--find", "COUNT")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out.strip(), "top.dut.count [3:0]")

    def test_clean_error_without_traceback(self):
        bad = self.path.with_name("bad.vcd")
        bad.write_text("$timescale 1 ns $end", encoding="utf-8")
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = vcdtui.main([str(bad), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("vcdtui: error:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
