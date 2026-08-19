#!/usr/bin/env python3
"""vcdtui: inspect VCD traces with the Python standard library."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "0.1.0-dev"


class VCDTUIError(Exception):
    """Expected user-facing error."""


class VCDParseError(VCDTUIError):
    """Malformed or unsupported VCD input."""


_TIME_UNITS = {
    "s": Fraction(1, 1),
    "ms": Fraction(1, 1_000),
    "us": Fraction(1, 1_000_000),
    "ns": Fraction(1, 1_000_000_000),
    "ps": Fraction(1, 1_000_000_000_000),
    "fs": Fraction(1, 1_000_000_000_000_000),
}
_TIME_UNIT_ORDER = ("s", "ms", "us", "ns", "ps", "fs")


@dataclass(frozen=True)
class TimeScale:
    coefficient: int
    unit: str

    @property
    def seconds_per_tick(self) -> Fraction:
        return self.coefficient * _TIME_UNITS[self.unit]

    def parse_ticks(self, text: str) -> int:
        value = text.strip().lower()
        if value.isdigit():
            return int(value)
        for unit in sorted(_TIME_UNITS, key=len, reverse=True):
            if value.endswith(unit):
                number = value[: -len(unit)]
                if not number.isdigit():
                    break
                ticks = Fraction(int(number), 1) * _TIME_UNITS[unit] / self.seconds_per_tick
                if ticks.denominator != 1:
                    raise VCDTUIError(
                        f"time {text!r} does not fall exactly on a VCD tick "
                        f"({self.coefficient}{self.unit})"
                    )
                return ticks.numerator
        raise VCDTUIError(f"invalid time {text!r}; use raw ticks or a unit such as 100ns")

    def format_tick(self, tick: int) -> str:
        if tick == 0:
            return f"0{self.unit}"
        seconds = tick * self.seconds_per_tick
        for unit in _TIME_UNIT_ORDER:
            value = seconds / _TIME_UNITS[unit]
            if value.denominator == 1:
                return f"{value.numerator}{unit}"
        return f"{tick} ticks"


@dataclass(frozen=True)
class Change:
    time: int
    value: str


@dataclass
class ValueStream:
    identifier: str
    width: int
    changes: List[Change] = field(default_factory=list)

    def add(self, time: int, value: str) -> None:
        change = Change(time, value)
        if self.changes and self.changes[-1].time == time:
            self.changes[-1] = change
        else:
            self.changes.append(change)

    def value_at(self, time: int) -> Optional[str]:
        index = bisect_right(self.changes, time, key=lambda change: change.time) - 1
        if index < 0:
            return None
        return self.changes[index].value

    def changes_between(self, start: int, end: int) -> Sequence[Change]:
        first = bisect_left(self.changes, start, key=lambda change: change.time)
        last = bisect_right(self.changes, end, key=lambda change: change.time)
        return self.changes[first:last]


@dataclass(frozen=True)
class Signal:
    full_name: str
    reference: str
    width: int
    var_type: str
    stream: ValueStream


@dataclass
class VCDFile:
    timescale: TimeScale
    signals: List[Signal]
    streams: Dict[str, ValueStream]
    last_time: int = 0

    def find(self, pattern: str) -> List[Signal]:
        needle = pattern.casefold()
        return [signal for signal in self.signals if needle in signal.full_name.casefold()]


class TokenStream:
    def __init__(self, tokens: Sequence[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def done(self) -> bool:
        return self.index >= len(self.tokens)

    def pop(self) -> str:
        if self.done():
            raise VCDParseError("unexpected end of file")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def collect_until_end(self) -> List[str]:
        values: List[str] = []
        while True:
            token = self.pop()
            if token == "$end":
                return values
            values.append(token)


def _parse_timescale(parts: Sequence[str]) -> TimeScale:
    if len(parts) == 1:
        text = parts[0].lower()
        digits = "".join(ch for ch in text if ch.isdigit())
        unit = text[len(digits) :]
    elif len(parts) == 2:
        digits, unit = parts[0], parts[1].lower()
    else:
        raise VCDParseError("invalid $timescale directive")
    if not digits.isdigit() or int(digits) <= 0 or unit not in _TIME_UNITS:
        raise VCDParseError(f"unsupported timescale: {' '.join(parts)}")
    return TimeScale(int(digits), unit)


def _normalize_vector(value: str, width: int) -> str:
    bits = value.lower()
    if not bits or any(ch not in "01xz" for ch in bits):
        raise VCDParseError(f"unsupported binary vector value {value!r}")
    if len(bits) > width:
        raise VCDParseError(f"vector value {value!r} exceeds declared width {width}")
    if len(bits) < width:
        pad = bits[0] if bits[0] in "xz" else "0"
        bits = pad * (width - len(bits)) + bits
    return bits


def parse_vcd_text(text: str) -> VCDFile:
    ts = TokenStream(text.split())
    scopes: List[str] = []
    streams: Dict[str, ValueStream] = {}
    signals: List[Signal] = []
    timescale: Optional[TimeScale] = None

    while not ts.done():
        token = ts.pop()
        if token == "$enddefinitions":
            trailing = ts.collect_until_end()
            if trailing:
                raise VCDParseError("unexpected tokens in $enddefinitions")
            break
        if token in ("$date", "$version", "$comment"):
            ts.collect_until_end()
            continue
        if token == "$timescale":
            timescale = _parse_timescale(ts.collect_until_end())
            continue
        if token == "$scope":
            parts = ts.collect_until_end()
            if len(parts) < 2:
                raise VCDParseError("invalid $scope directive")
            scopes.append(parts[1])
            continue
        if token == "$upscope":
            parts = ts.collect_until_end()
            if parts:
                raise VCDParseError("unexpected tokens in $upscope")
            if not scopes:
                raise VCDParseError("$upscope without matching $scope")
            scopes.pop()
            continue
        if token == "$var":
            parts = ts.collect_until_end()
            if len(parts) < 4:
                raise VCDParseError("invalid $var directive")
            var_type, width_text, identifier = parts[:3]
            if not width_text.isdigit() or int(width_text) <= 0:
                raise VCDParseError(f"invalid width in $var: {width_text!r}")
            width = int(width_text)
            reference = " ".join(parts[3:])
            stream = streams.get(identifier)
            if stream is None:
                stream = ValueStream(identifier=identifier, width=width)
                streams[identifier] = stream
            elif stream.width != width:
                raise VCDParseError(
                    f"identifier {identifier!r} is declared with incompatible widths "
                    f"{stream.width} and {width}"
                )
            full_name = ".".join(scopes + [reference]) if scopes else reference
            signals.append(Signal(full_name, reference, width, var_type, stream))
            continue
        if token.startswith("$"):
            raise VCDParseError(f"unsupported header directive {token}")
        raise VCDParseError(f"unexpected header token {token!r}")
    else:
        raise VCDParseError("missing $enddefinitions")

    if timescale is None:
        raise VCDParseError("missing $timescale")
    if scopes:
        raise VCDParseError("unclosed $scope at $enddefinitions")

    current_time = 0
    last_time = 0
    in_dumpvars = False

    while not ts.done():
        token = ts.pop()
        if token == "$dumpvars":
            if in_dumpvars:
                raise VCDParseError("nested $dumpvars")
            in_dumpvars = True
            continue
        if token == "$end" and in_dumpvars:
            in_dumpvars = False
            continue
        if token.startswith("$"):
            raise VCDParseError(f"unsupported value-change directive {token}")
        if token.startswith("#"):
            stamp = token[1:]
            if not stamp.isdigit():
                raise VCDParseError(f"invalid timestamp {token!r}")
            new_time = int(stamp)
            if new_time < current_time:
                raise VCDParseError("timestamps must be nondecreasing")
            current_time = new_time
            last_time = max(last_time, current_time)
            continue
        first = token[:1].lower()
        if first in "01xz" and len(token) > 1:
            identifier = token[1:]
            stream = streams.get(identifier)
            if stream is None:
                raise VCDParseError(f"value change for unknown identifier {identifier!r}")
            if stream.width != 1:
                raise VCDParseError(
                    f"scalar value used for {identifier!r}, declared width {stream.width}"
                )
            stream.add(current_time, first)
            continue
        if first == "b" and len(token) > 1:
            raw = token[1:]
            identifier = ts.pop()
            stream = streams.get(identifier)
            if stream is None:
                raise VCDParseError(f"value change for unknown identifier {identifier!r}")
            stream.add(current_time, _normalize_vector(raw, stream.width))
            continue
        if first in ("r", "s"):
            kind = "real" if first == "r" else "string"
            raise VCDParseError(f"{kind} value changes are not supported")
        raise VCDParseError(f"unsupported value-change token {token!r}")

    if in_dumpvars:
        raise VCDParseError("unterminated $dumpvars")
    return VCDFile(timescale=timescale, signals=signals, streams=streams, last_time=last_time)


def parse_vcd(path: Path) -> VCDFile:
    try:
        return parse_vcd_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VCDTUIError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeError as exc:
        raise VCDTUIError(f"cannot decode {path} as UTF-8") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vcdtui",
        description="Inspect VCD traces using only the Python standard library.",
    )
    parser.add_argument("file", nargs="?", type=Path, help="VCD file to inspect")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="show tracebacks for errors")
    parser.add_argument("--list", action="store_true", help="list available signals and exit")
    parser.add_argument("--find", metavar="PATTERN", help="find matching signals and exit")
    parser.add_argument(
        "-s",
        "--signals",
        metavar="SELECTORS",
        help="comma-separated signal names or substrings to display",
    )
    parser.add_argument("--from", dest="time_from", metavar="TIME", help="start time")
    parser.add_argument("--to", dest="time_to", metavar="TIME", help="end time")
    parser.add_argument("--dump", action="store_true", help="render a deterministic timeline to stdout")
    parser.add_argument("--ascii", action="store_true", help="use ASCII drawing characters")
    parser.add_argument("--no-color", action="store_true", help="disable terminal colors")
    return parser


def _require_file(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    if args.file is None:
        parser.error("a VCD file is required")
    return args.file


def _print_signals(signals: Iterable[Signal]) -> None:
    for signal in signals:
        print(signal.full_name)


def select_signals(vcd: VCDFile, selectors: Optional[str]) -> List[Signal]:
    if selectors is None:
        if not vcd.signals:
            raise VCDTUIError("trace contains no signals")
        return list(vcd.signals)

    requested = [part.strip() for part in selectors.split(",")]
    if not requested or any(not part for part in requested):
        raise VCDTUIError("--signals requires non-empty comma-separated selectors")

    selected_indexes = set()
    for selector in requested:
        needle = selector.casefold()
        exact = [
            index
            for index, signal in enumerate(vcd.signals)
            if signal.full_name.casefold() == needle or signal.reference.casefold() == needle
        ]
        matches = exact or [
            index
            for index, signal in enumerate(vcd.signals)
            if needle in signal.full_name.casefold()
        ]
        if not matches:
            raise VCDTUIError(f"requested signal {selector!r} was not found")
        selected_indexes.update(matches)

    return [signal for index, signal in enumerate(vcd.signals) if index in selected_indexes]


def resolve_range(vcd: VCDFile, start_text: Optional[str], end_text: Optional[str]) -> Tuple[int, int]:
    start = vcd.timescale.parse_ticks(start_text) if start_text is not None else 0
    end = vcd.timescale.parse_ticks(end_text) if end_text is not None else vcd.last_time
    if start > end:
        raise VCDTUIError(f"invalid time range: start tick {start} is after end tick {end}")
    if start > vcd.last_time:
        raise VCDTUIError(
            f"range starts at tick {start}, beyond the final VCD timestamp {vcd.last_time}"
        )
    if end > vcd.last_time:
        raise VCDTUIError(
            f"range ends at tick {end}, beyond the final VCD timestamp {vcd.last_time}"
        )
    return start, end


def _event_times(signals: Sequence[Signal], start: int, end: int) -> List[int]:
    times = {start, end}
    seen_streams = set()
    for signal in signals:
        key = id(signal.stream)
        if key in seen_streams:
            continue
        seen_streams.add(key)
        times.update(change.time for change in signal.stream.changes_between(start, end))
    return sorted(times)


def _raw_dump_rows(
    vcd: VCDFile,
    signals: Sequence[Signal],
    start: int,
    end: int,
) -> Tuple[List[str], List[List[str]]]:
    headers = ["tick", "time"] + [signal.full_name for signal in signals]
    rows: List[List[str]] = []
    for tick in _event_times(signals, start, end):
        values = [signal.stream.value_at(tick) or "?" for signal in signals]
        rows.append([str(tick), vcd.timescale.format_tick(tick)] + values)
    return headers, rows


def _color_value(signal: Signal, value: str, enabled: bool) -> str:
    if not enabled or value == "?":
        return value
    if "x" in value:
        color = "31"  # red
    elif "z" in value:
        color = "35"  # magenta
    elif signal.width == 1:
        color = "32"  # green
    else:
        color = "36"  # cyan
    return f"\x1b[{color}m{value}\x1b[0m"


def render_dump(
    vcd: VCDFile,
    signals: Sequence[Signal],
    start: int,
    end: int,
    *,
    ascii_only: bool,
    color: bool,
) -> str:
    headers, rows = _raw_dump_rows(vcd, signals, start, end)
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    separator = " | " if ascii_only else " │ "
    cross = "+" if ascii_only else "┼"
    horizontal = "-" if ascii_only else "─"

    def plain_line(cells: Sequence[str]) -> str:
        return separator.join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    divider_parts = []
    last_index = len(widths) - 1
    for index, width in enumerate(widths):
        padding = 1 if index in (0, last_index) else 2
        divider_parts.append(horizontal * (width + padding))

    output = [
        f"timescale: {vcd.timescale.coefficient} {vcd.timescale.unit}",
        f"range: {start}..{end} ticks",
        f"signals: {len(signals)}",
        plain_line(headers),
        cross.join(divider_parts),
    ]

    for row in rows:
        cells = list(row)
        rendered_values = []
        for signal, value in zip(signals, row[2:]):
            rendered_values.append(_color_value(signal, value, color))
        visible = cells[:2] + rendered_values
        padded = []
        for index, cell in enumerate(visible):
            if index < 2 or not color:
                padded.append(cell.ljust(widths[index]))
            else:
                raw = row[index]
                padding = " " * (widths[index] - len(raw))
                padded.append(cell + padding)
        output.append(separator.join(padded).rstrip())
    return "\n".join(output) + "\n"


def _stdout_supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    path = _require_file(args, parser)
    vcd = parse_vcd(path)

    if args.list:
        _print_signals(vcd.signals)
        return 0
    if args.find is not None:
        _print_signals(vcd.find(args.find))
        return 0

    signals = select_signals(vcd, args.signals)
    start, end = resolve_range(vcd, args.time_from, args.time_to)

    if args.dump:
        print(
            render_dump(
                vcd,
                signals,
                start,
                end,
                ascii_only=args.ascii,
                color=not args.no_color and _stdout_supports_color(),
            ),
            end="",
        )
        return 0

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise VCDTUIError("interactive mode requires a terminal; use --dump for non-interactive output")
    raise VCDTUIError("interactive mode is planned for Milestone 3 and is not implemented yet")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args, parser)
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        elif isinstance(exc, VCDTUIError):
            print(f"vcdtui: error: {exc}", file=sys.stderr)
        else:
            print(f"vcdtui: error: unexpected failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
