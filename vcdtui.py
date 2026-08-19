#!/usr/bin/env python3
"""vcdtui: inspect VCD traces with the Python standard library."""

from __future__ import annotations

import argparse
import sys
import traceback
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
    parser.add_argument("-s", "--signals", metavar="PATTERN", help="signals to display")
    parser.add_argument("--from", dest="time_from", metavar="TIME", help="start time")
    parser.add_argument("--to", dest="time_to", metavar="TIME", help="end time")
    parser.add_argument("--dump", action="store_true", help="render to stdout instead of opening the TUI")
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


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    path = _require_file(args, parser)
    vcd = parse_vcd(path)

    if args.time_from is not None:
        vcd.timescale.parse_ticks(args.time_from)
    if args.time_to is not None:
        vcd.timescale.parse_ticks(args.time_to)

    if args.list:
        _print_signals(vcd.signals)
        return 0
    if args.find is not None:
        _print_signals(vcd.find(args.find))
        return 0
    if args.dump:
        raise VCDTUIError("--dump is planned for Milestone 2 and is not implemented yet")

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
