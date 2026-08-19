"""Every file in examples/qualification/ behaves as its directory claims.

A corpus that nothing exercises drifts out of date silently, which is exactly
what happened when real values and truncated traces became supported.
"""

import unittest
from pathlib import Path

import vcdtui


CORPUS = Path(__file__).resolve().parent.parent / "examples" / "qualification"


def traces(subdirectory: str = "") -> list:
    root = CORPUS / subdirectory if subdirectory else CORPUS
    return sorted(path for path in root.glob("*.vcd"))


class CorpusLayoutTests(unittest.TestCase):
    def test_the_corpus_exists_and_is_populated(self):
        self.assertTrue(traces(), CORPUS)
        for name in ("malformed", "truncated", "generated"):
            self.assertTrue(traces(name), CORPUS / name)

    def test_every_trace_is_listed_in_the_readme(self):
        readme = (CORPUS / "README.md").read_text(encoding="utf-8")
        for group in ("", "malformed", "truncated", "generated"):
            for path in traces(group):
                self.assertIn(path.name, readme, path)


class SupportedTraceTests(unittest.TestCase):
    def test_supported_traces_parse_without_warnings(self):
        for path in traces():
            with self.subTest(trace=path.name):
                vcd = vcdtui.parse_vcd(path)
                self.assertEqual(vcd.warnings, [])
                self.assertTrue(vcd.signals)

    def test_generated_traces_parse_without_warnings(self):
        for path in traces("generated"):
            with self.subTest(trace=path.name):
                vcd = vcdtui.parse_vcd(path)
                self.assertEqual(vcd.warnings, [])
                self.assertTrue(vcd.signals)

    def test_supported_traces_render_a_deterministic_dump(self):
        for path in traces() + traces("generated"):
            with self.subTest(trace=path.name):
                vcd = vcdtui.parse_vcd(path)
                start, end = vcdtui.resolve_range(vcd, None, None)
                rendered = vcdtui.render_dump(
                    vcd, vcd.signals, start, end, ascii_only=True, color=False
                )
                self.assertTrue(rendered.endswith("\n"))
                self.assertTrue(rendered.isascii(), path.name)


class TruncatedTraceTests(unittest.TestCase):
    def test_truncated_traces_are_recovered_with_a_warning(self):
        for path in traces("truncated"):
            with self.subTest(trace=path.name):
                vcd = vcdtui.parse_vcd(path)
                self.assertTrue(vcd.signals)
                self.assertEqual(len(vcd.warnings), 1)
                self.assertIn("truncated", vcd.warnings[0])


class MalformedTraceTests(unittest.TestCase):
    def test_malformed_traces_fail_with_a_parse_error(self):
        for path in traces("malformed"):
            with self.subTest(trace=path.name):
                with self.assertRaises(vcdtui.VCDParseError):
                    vcdtui.parse_vcd(path)

    def test_malformed_failures_name_the_file_and_the_line(self):
        for path in traces("malformed"):
            with self.subTest(trace=path.name):
                try:
                    vcdtui.parse_vcd(path)
                except vcdtui.VCDParseError as exc:
                    self.assertIn(path.name, str(exc))
                    self.assertIn("line ", str(exc))


class IcarusBaselineTests(unittest.TestCase):
    """The trace that motivated the dump-control and real-value work."""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd(CORPUS / "generated" / "icarus12_dump_control.vcd")

    def test_names_carry_no_declared_bit_range(self):
        self.assertIn("top.count", [s.full_name for s in self.vcd.signals])
        self.assertEqual(
            next(s for s in self.vcd.signals if s.reference == "count").bit_range, "[7:0]"
        )

    def test_the_dumpall_before_the_first_timestamp_is_recorded(self):
        width = next(s for s in self.vcd.signals if s.reference == "WIDTH")
        self.assertEqual(width.stream.value_at(0), "00000000000000000000000000000100")

    def test_the_real_keeps_its_textual_value_including_nan(self):
        real = next(s for s in self.vcd.signals if s.reference == "r")
        self.assertEqual(real.stream.kind, "real")
        self.assertEqual([c.value for c in real.stream.changes][:3], ["1.5", "2.25", "NaN"])

    def test_the_dumpoff_checkpoint_marks_bits_unknown(self):
        clk = next(s for s in self.vcd.signals if s.full_name == "top.clk")
        self.assertEqual(clk.stream.value_at(25), "x")

    def test_an_alias_shares_one_stream(self):
        top_clk = next(s for s in self.vcd.signals if s.full_name == "top.clk")
        sub_clk = next(s for s in self.vcd.signals if s.full_name == "top.u_sub.clk")
        self.assertIs(top_clk.stream, sub_clk.stream)


if __name__ == "__main__":
    unittest.main()
