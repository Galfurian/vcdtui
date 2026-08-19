"""Process-level behavior: interrupts, closed pipes, interpreter version, times."""

import contextlib
import io
import sys
import unittest
from fractions import Fraction

import vcdtui


class InterruptTests(unittest.TestCase):
    def run_main(self, error):
        def boom(args, parser):
            raise error

        original, vcdtui.run = vcdtui.run, boom
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = vcdtui.main(["trace.vcd"])
        finally:
            vcdtui.run = original
        return code, out.getvalue(), err.getvalue()

    def test_keyboard_interrupt_exits_cleanly(self):
        code, _, err = self.run_main(KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assertNotIn("Traceback", err)

    def test_broken_pipe_exits_cleanly_and_silently(self):
        code, out, err = self.run_main(BrokenPipeError())
        self.assertEqual(code, 141)
        self.assertEqual(err, "")
        self.assertEqual(out, "")

    def test_expected_error_still_reports_concisely(self):
        code, _, err = self.run_main(vcdtui.VCDTUIError("nope"))
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), "vcdtui: error: nope")


class PythonVersionTests(unittest.TestCase):
    def test_supported_version_passes(self):
        self.assertIsNone(vcdtui.python_version_error((3, 10, 0)))
        self.assertIsNone(vcdtui.python_version_error(sys.version_info))

    def test_old_version_is_reported_before_anything_else_fails(self):
        message = vcdtui.python_version_error((3, 8, 10))
        self.assertIsNotNone(message)
        self.assertIn("3.10", message)
        self.assertIn("3.8", message)


class TimeParsingTests(unittest.TestCase):
    def setUp(self):
        self.scale = vcdtui.TimeScale(10, "ps")

    def test_raw_ticks(self):
        self.assertEqual(self.scale.parse_ticks("42"), 42)

    def test_integer_physical_time(self):
        self.assertEqual(self.scale.parse_ticks("1ns"), 100)

    def test_fractional_physical_time_is_exact(self):
        self.assertEqual(self.scale.parse_ticks("1.5ns"), 150)
        self.assertEqual(self.scale.parse_ticks("0.25ns"), 25)

    def test_fractional_time_off_the_grid_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "does not fall exactly"):
            self.scale.parse_ticks("1.05ps")

    def test_uppercase_and_padded_input(self):
        self.assertEqual(self.scale.parse_ticks(" 1NS "), 100)

    def test_negative_time_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "invalid time"):
            self.scale.parse_ticks("-5ns")

    def test_garbage_is_rejected(self):
        for text in ("", "ns", "1.2.3ns", "1e9ns", "1 ns", "1parsec"):
            with self.assertRaisesRegex(vcdtui.VCDTUIError, "invalid time"):
                self.scale.parse_ticks(text)

    def test_no_floating_point_is_involved(self):
        self.assertEqual(self.scale.seconds_per_tick, Fraction(1, 100_000_000_000))


class RangeTests(unittest.TestCase):
    TEXT = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$upscope $end
$enddefinitions $end
#0
0!
#100
1!
"""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(self.TEXT)

    def test_default_range_covers_the_trace(self):
        self.assertEqual(vcdtui.resolve_range(self.vcd, None, None), (0, 100))

    def test_out_of_range_error_states_the_traces_own_end(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, r"100ns"):
            vcdtui.resolve_range(self.vcd, None, "200ns")


class EmptyTraceTests(unittest.TestCase):
    TEXT = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$upscope $end
$enddefinitions $end
"""

    def test_trace_without_value_changes_is_usable(self):
        vcd = vcdtui.parse_vcd_text(self.TEXT)
        self.assertEqual(vcdtui.resolve_range(vcd, None, None), (0, 0))
        rendered = vcdtui.render_dump(
            vcd, vcd.signals, 0, 0, ascii_only=True, color=False
        )
        self.assertIn("top.clk", rendered)

    def test_trace_without_signals_reports_a_clean_error(self):
        text = "$timescale 1 ns $end\n$enddefinitions $end\n"
        vcd = vcdtui.parse_vcd_text(text)
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "no signals"):
            vcdtui.select_signals(vcd, None)


if __name__ == "__main__":
    unittest.main()
