import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 8 \" data [7:0] $end
$var wire 3 # state [2:0] $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b00000000 \"
b000 #
$end
#10
1!
#20
0!
b00010010 \"
#30
b001 #
#40
1!
#50
b11111111 \"
#60
0!
b010 #
#80
1!
"""


class DumpWaveTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def test_default_render_fits_eighty_columns(self):
        rendered = vcdtui.render_wave_dump(
            self.vcd,
            self.vcd.signals,
            0,
            self.vcd.last_time,
            width=80,
            ascii_only=False,
        )
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 2 + len(self.vcd.signals))
        self.assertTrue(all(len(line) <= 80 for line in lines))
        self.assertTrue(any("clk" in line for line in lines))
        self.assertTrue(any("data[7:0]" in line for line in lines))
        self.assertIn("0ns", lines[0])
        self.assertIn("80ns", lines[0])

    def test_custom_width_is_total_line_width(self):
        rendered = vcdtui.render_wave_dump(
            self.vcd,
            self.vcd.signals,
            0,
            self.vcd.last_time,
            width=48,
            ascii_only=True,
        )
        self.assertTrue(all(len(line) <= 48 for line in rendered.splitlines()))
        self.assertEqual(len(rendered.splitlines()[1]), 48)

    def test_too_narrow_wave_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "at least 32"):
            vcdtui.render_wave_dump(
                self.vcd,
                self.vcd.signals,
                0,
                self.vcd.last_time,
                width=31,
                ascii_only=False,
            )


class DumpWaveCLITests(unittest.TestCase):
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

    def test_dump_wave_defaults_to_eighty_columns(self):
        code, out, err = self.run_main("-s", "clk,data", "--dump-wave", "--ascii")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(all(len(line) <= 80 for line in out.splitlines()))
        self.assertEqual(len(out.splitlines()), 4)

    def test_wave_width_controls_total_output_width(self):
        code, out, err = self.run_main(
            "-s", "clk,data", "--dump-wave", "--wave-width", "48", "--ascii"
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(all(len(line) <= 48 for line in out.splitlines()))

    def test_dump_and_dump_wave_are_mutually_exclusive(self):
        code, out, err = self.run_main("--dump", "--dump-wave")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("mutually exclusive", err)


if __name__ == "__main__":
    unittest.main()
