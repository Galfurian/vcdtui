"""Splitting a long selection across several -s options.

A comma-separated list is fine in a shell but unreadable in a Makefile or on a
slide, where the natural form is one selector per line.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import vcdtui

from tests.test_scope_view import SAMPLE


class RepeatedSelectorTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)

    def select(self, selectors):
        chosen = vcdtui.select_signals(self.vcd, selectors)
        return [signal.full_name for signal in chosen]

    def test_a_list_of_selectors_is_accepted(self):
        self.assertEqual(
            self.select(["dut4.clk", "start"]),
            ["tb_counter.start", "tb_counter.dut4.clk"],
        )

    def test_a_single_string_still_works(self):
        self.assertEqual(self.select("dut4.clk"), ["tb_counter.dut4.clk"])

    def test_each_entry_may_itself_be_comma_separated(self):
        self.assertEqual(
            self.select(["dut4.clk,dut8.clk", "start"]),
            ["tb_counter.start", "tb_counter.dut4.clk", "tb_counter.dut8.clk"],
        )

    def test_repeats_are_deduplicated(self):
        self.assertEqual(self.select(["start", "start"]), ["tb_counter.start"])

    def test_an_empty_entry_is_an_error(self):
        with self.assertRaisesRegex(vcdtui.VCDTUIError, "non-empty"):
            self.select(["start", ""])

    def test_an_empty_list_selects_everything(self):
        # Consistent with omitting --signals entirely: there is nothing to narrow.
        self.assertEqual(len(self.select([])), 9)


class RepeatedOptionCLITests(unittest.TestCase):
    def run_cli(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tb.vcd"
            path.write_text(SAMPLE, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = vcdtui.main([str(path), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_the_option_can_be_repeated(self):
        code, out, err = self.run_cli(
            [
                "--scope",
                "tb_counter",
                "-s",
                "clk",
                "-s",
                "start",
                "-s",
                "dut8.value",
                "--dump",
                "--ascii",
                "--no-color",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        header = next(line for line in out.splitlines() if line.startswith("tick"))
        self.assertIn("clk", header)
        self.assertIn("start", header)
        self.assertIn("dut8.value[7:0]", header)

    def test_a_single_comma_separated_option_is_unchanged(self):
        code, out, _ = self.run_cli(
            ["-s", "dut4.clk,dut8.clk", "--dump", "--ascii", "--no-color"]
        )
        self.assertEqual(code, 0)
        self.assertIn("signals: 2", out)


if __name__ == "__main__":
    unittest.main()
