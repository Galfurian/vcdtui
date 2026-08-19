import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import vcdtui


SAMPLE = """\
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


class DumpTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def test_value_at_and_range(self):
        clk = self.vcd.streams["!"]
        self.assertEqual(clk.value_at(0), "0")
        self.assertEqual(clk.value_at(15), "1")
        self.assertEqual(clk.value_at(20), "0")
        self.assertEqual([c.time for c in clk.changes_between(10, 20)], [10, 20])

    def test_signal_selection_prefers_exact_names(self):
        selected = vcdtui.select_signals(self.vcd, "top.dut.clk,count")
        self.assertEqual([s.reference for s in selected], ["clk", "count [3:0]"])

    def test_missing_signal_is_error(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "was not found"):
            vcdtui.select_signals(self.vcd, "missing")

    def test_range_is_exact_and_bounded(self):
        self.assertEqual(vcdtui.resolve_range(self.vcd, "100ps", "200ps"), (10, 20))
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "beyond the final"):
            vcdtui.resolve_range(self.vcd, None, "210ps")

    def test_ascii_dump_snapshot(self):
        signals = vcdtui.select_signals(self.vcd, "top.dut.clk,count")
        rendered = vcdtui.render_dump(
            self.vcd,
            signals,
            10,
            20,
            ascii_only=True,
            color=False,
        )
        self.assertEqual(
            rendered,
            """\
timescale: 10 ps
range: 10..20 ticks
signals: 2
tick | time  | top.dut.clk | top.dut.count [3:0]
-----+-------+-------------+--------------------
10   | 100ps | 1           | 0011
20   | 200ps | 0           | 0010
""",
        )

    def test_unicode_dump_uses_unicode_separators(self):
        signals = vcdtui.select_signals(self.vcd, "count")
        rendered = vcdtui.render_dump(
            self.vcd,
            signals,
            0,
            10,
            ascii_only=False,
            color=False,
        )
        self.assertIn(" │ ", rendered)
        self.assertIn("┼", rendered)

    def test_dump_cli_is_noninteractive_and_colorless_when_redirected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.vcd"
            path.write_text(SAMPLE, encoding="utf-8")
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = vcdtui.main([
                    str(path),
                    "--signals", "top.dut.clk,count",
                    "--from", "100ps",
                    "--to", "200ps",
                    "--dump",
                    "--ascii",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertNotIn("\x1b[", out.getvalue())
            self.assertIn("10   | 100ps | 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
