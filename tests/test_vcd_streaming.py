"""Streaming tokenizer: line numbers in errors, and non-VCD input handling."""

import tempfile
import unittest
from pathlib import Path

import vcdtui


HEADER = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$upscope $end
$enddefinitions $end
"""


class LineNumberTests(unittest.TestCase):
    def test_header_error_reports_its_line(self):
        text = "$timescale 1 ns $end\n$scope module top $end\n$bogus x $end\n"
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"line 3: unsupported header directive"):
            vcdtui.parse_vcd_text(text)

    def test_value_change_error_reports_its_line(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"line 8: invalid timestamp"):
            vcdtui.parse_vcd_text(HEADER + "#0\n0!\n#abc\n")

    def test_multiline_directive_error_reports_the_offending_line(self):
        text = "$timescale\n  1\n  parsecs\n$end\n"
        with self.assertRaisesRegex(vcdtui.VCDParseError, r"line 4: unsupported timescale"):
            vcdtui.parse_vcd_text(text)

    def test_parse_error_from_a_file_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.vcd"
            path.write_text(HEADER + "#0\n$nope\n", encoding="utf-8")
            with self.assertRaisesRegex(vcdtui.VCDParseError, r"broken\.vcd: line 7:"):
                vcdtui.parse_vcd(path)


class NonVCDInputTests(unittest.TestCase):
    def test_empty_input_is_rejected_clearly(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "empty"):
            vcdtui.parse_vcd_text("")

    def test_whitespace_only_input_is_rejected_clearly(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "empty"):
            vcdtui.parse_vcd_text("\n\n   \n")

    def test_input_that_is_not_a_vcd_is_rejected_clearly(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "does not look like a VCD file"):
            vcdtui.parse_vcd_text("module top;\n  reg clk;\nendmodule\n")

    def test_byte_order_mark_is_tolerated(self):
        vcd = vcdtui.parse_vcd_text("﻿" + HEADER + "#0\n0!\n")
        self.assertEqual(vcd.signals[0].full_name, "top.clk")

    def test_crlf_line_endings_are_tolerated(self):
        vcd = vcdtui.parse_vcd_text((HEADER + "#0\n0!\n").replace("\n", "\r\n"))
        self.assertEqual(vcd.signals[0].full_name, "top.clk")

    def test_undecodable_bytes_do_not_abort_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latin1.vcd"
            path.write_bytes(
                b"$comment r\xe9sum\xe9 $end\n" + (HEADER + "#0\n0!\n").encode("utf-8")
            )
            vcd = vcdtui.parse_vcd(path)
            self.assertEqual(vcd.signals[0].full_name, "top.clk")

    def test_directory_argument_reports_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(vcdtui.VCDTUIError) as caught:
                vcdtui.parse_vcd(Path(tmp))
            self.assertNotIsInstance(caught.exception, vcdtui.VCDParseError)


class StreamingTests(unittest.TestCase):
    def test_token_stream_does_not_consume_its_source_eagerly(self):
        produced = []

        def source():
            for line, token in enumerate(("$timescale", "1", "ns", "$end"), start=1):
                produced.append(token)
                yield token, line

        stream = vcdtui.TokenStream(source())
        self.assertEqual(produced, [])
        self.assertEqual(stream.pop(), "$timescale")
        self.assertLessEqual(len(produced), 2)

    def test_token_stream_reports_the_line_of_the_last_token(self):
        stream = vcdtui.TokenStream(iter([("$end", 7)]))
        stream.pop()
        self.assertEqual(stream.line, 7)

    def test_a_large_trace_parses_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.vcd"
            with path.open("w", encoding="utf-8") as handle:
                handle.write(HEADER)
                for tick in range(100_000):
                    handle.write(f"#{tick}\n{tick & 1}!\n")
            vcd = vcdtui.parse_vcd(path)
        self.assertEqual(vcd.last_time, 99_999)
        self.assertEqual(len(vcd.streams["!"].changes), 100_000)


if __name__ == "__main__":
    unittest.main()
