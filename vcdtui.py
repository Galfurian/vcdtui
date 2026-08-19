#!/usr/bin/env python3
"""Terminal-first VCD waveform viewer using only the Python standard library."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


PROGRAM = "vcdtui"
VERSION = "0.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Inspect Value Change Dump (VCD) traces from the terminal. "
            "Interactive viewing is the default; query and dump modes are "
            "available for scripts and captured output."
        ),
    )
    parser.add_argument("file", type=Path, nargs="?", help="VCD file to inspect")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    query = parser.add_argument_group("query")
    query.add_argument(
        "--list",
        action="store_true",
        help="list available signals and exit",
    )
    query.add_argument(
        "--find",
        metavar="PATTERN",
        help="list signals matching PATTERN and exit",
    )
    query.add_argument(
        "-s",
        "--signals",
        metavar="PATTERN[,PATTERN...]",
        help="restrict displayed signals",
    )

    window = parser.add_argument_group("time window")
    window.add_argument(
        "--from",
        dest="time_from",
        metavar="TIME",
        help="start time, for example 100ns",
    )
    window.add_argument(
        "--to",
        dest="time_to",
        metavar="TIME",
        help="end time, for example 250ns",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--dump",
        action="store_true",
        help="render to stdout instead of opening the interactive UI",
    )
    output.add_argument(
        "--ascii",
        action="store_true",
        help="use ASCII drawing characters instead of Unicode",
    )
    output.add_argument(
        "--no-color",
        action="store_true",
        help="disable terminal colors",
    )

    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.file is None:
        parser.error("the following arguments are required: file")

    if args.time_from and args.time_to and args.time_from == args.time_to:
        parser.error("--from and --to must describe a non-empty time window")


def run(args: argparse.Namespace) -> int:
    """Dispatch the selected mode.

    The parser, waveform model, renderer, and curses application will be wired
    here as the implementation milestones land. Keeping dispatch separate from
    argument parsing makes CLI behavior straightforward to test.
    """
    if not args.file.exists():
        print(f"{PROGRAM}: {args.file}: file not found", file=sys.stderr)
        return 2

    print(
        f"{PROGRAM}: scaffold only; VCD parsing is not implemented yet",
        file=sys.stderr,
    )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
