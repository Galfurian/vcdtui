from __future__ import annotations

import argparse
from pathlib import Path
import unittest

import vcdtui


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = vcdtui.build_parser()

    def test_file_is_parsed_as_path(self) -> None:
        args = self.parser.parse_args(["trace.vcd"])
        self.assertEqual(args.file, Path("trace.vcd"))

    def test_list_mode(self) -> None:
        args = self.parser.parse_args(["trace.vcd", "--list"])
        self.assertTrue(args.list)

    def test_find_mode(self) -> None:
        args = self.parser.parse_args(["trace.vcd", "--find", "count"])
        self.assertEqual(args.find, "count")

    def test_signal_filter(self) -> None:
        args = self.parser.parse_args(
            ["trace.vcd", "--signals", "clk,start,count"]
        )
        self.assertEqual(args.signals, "clk,start,count")

    def test_time_window(self) -> None:
        args = self.parser.parse_args(
            ["trace.vcd", "--from", "100ns", "--to", "250ns"]
        )
        self.assertEqual(args.time_from, "100ns")
        self.assertEqual(args.time_to, "250ns")

    def test_output_modes(self) -> None:
        args = self.parser.parse_args(
            ["trace.vcd", "--dump", "--ascii", "--no-color"]
        )
        self.assertTrue(args.dump)
        self.assertTrue(args.ascii)
        self.assertTrue(args.no_color)


class ValidationTests(unittest.TestCase):
    def test_missing_file_argument_is_rejected_by_validation(self) -> None:
        parser = vcdtui.build_parser()
        args = parser.parse_args([])
        with self.assertRaises(SystemExit):
            vcdtui.validate_args(parser, args)

    def test_empty_time_window_is_rejected(self) -> None:
        parser = vcdtui.build_parser()
        args = parser.parse_args(
            ["trace.vcd", "--from", "100ns", "--to", "100ns"]
        )
        with self.assertRaises(SystemExit):
            vcdtui.validate_args(parser, args)


if __name__ == "__main__":
    unittest.main()
