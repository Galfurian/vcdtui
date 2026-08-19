#!/usr/bin/env python3
"""vcdtui: inspect VCD traces with the Python standard library."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

__version__ = "0.2.0"

MINIMUM_PYTHON = (3, 10)


def python_version_error(version: Sequence[int]) -> Optional[str]:
    """Return a concise message when ``version`` is too old, else None."""
    if tuple(version[:2]) >= MINIMUM_PYTHON:
        return None
    return (
        "vcdtui: error: Python {}.{} or newer is required, "
        "found {}.{}".format(*MINIMUM_PYTHON, *version[:2])
    )


# Checked here rather than in main(): the module body itself uses 3.10 features,
# so an older interpreter must not reach them and fail with a traceback.
_VERSION_ERROR = python_version_error(sys.version_info)
if _VERSION_ERROR is not None:  # pragma: no cover - depends on the interpreter
    raise SystemExit(_VERSION_ERROR)


class VCDTUIError(Exception):
    """Expected user-facing error."""


class VCDParseError(VCDTUIError):
    """Malformed or unsupported VCD input."""


class VCDTruncatedError(VCDParseError):
    """The input ended while a construct was still being read.

    Distinguished from other parse errors because a trace whose value changes
    simply stop is recoverable, while malformed input is not.
    """


_TIME_UNITS = {
    "s": Fraction(1, 1),
    "ms": Fraction(1, 1_000),
    "us": Fraction(1, 1_000_000),
    "ns": Fraction(1, 1_000_000_000),
    "ps": Fraction(1, 1_000_000_000_000),
    "fs": Fraction(1, 1_000_000_000_000_000),
}
_TIME_UNIT_ORDER = ("s", "ms", "us", "ns", "ps", "fs")


def _is_decimal(text: str) -> bool:
    """True for a nonnegative decimal literal such as "1" or "1.5"."""
    whole, dot, fraction = text.partition(".")
    if dot:
        return whole.isdigit() and fraction.isdigit()
    return whole.isdigit()


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
            if not value.endswith(unit):
                continue
            number = value[: -len(unit)]
            if not _is_decimal(number):
                break
            # Fraction parses "1.5" exactly, so fractional times stay off floats.
            ticks = Fraction(number) * _TIME_UNITS[unit] / self.seconds_per_tick
            if ticks.denominator != 1:
                raise VCDTUIError(
                    f"time {text!r} does not fall exactly on a VCD tick "
                    f"({self.coefficient}{self.unit})"
                )
            return ticks.numerator
        raise VCDTUIError(
            f"invalid time {text!r}; use raw ticks or a unit such as 100ns or 1.5us"
        )

    def format_tick(self, tick: int) -> str:
        if tick == 0:
            return f"0{self.unit}"
        seconds = tick * self.seconds_per_tick
        for unit in _TIME_UNIT_ORDER:
            value = seconds / _TIME_UNITS[unit]
            if value.denominator == 1:
                return f"{value.numerator}{unit}"
        return f"{tick} ticks"


@dataclass(frozen=True, slots=True)
class Change:
    time: int
    value: str


@dataclass(slots=True)
class ValueStream:
    identifier: str
    width: int
    kind: str = "bit"
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

    def value_before(self, time: int) -> Optional[str]:
        index = bisect_left(self.changes, time, key=lambda change: change.time) - 1
        if index < 0:
            return None
        return self.changes[index].value

    def changes_between(self, start: int, end: int) -> Sequence[Change]:
        first = bisect_left(self.changes, start, key=lambda change: change.time)
        last = bisect_right(self.changes, end, key=lambda change: change.time)
        return self.changes[first:last]


@dataclass(frozen=True, slots=True)
class Signal:
    full_name: str
    reference: str
    width: int
    var_type: str
    stream: ValueStream
    bit_range: str = ""

    @property
    def display_name(self) -> str:
        """Hierarchical name with the declared bit range, as VCD writers show it."""
        return f"{self.full_name}{self.bit_range}"

    @property
    def display_reference(self) -> str:
        """Leaf name with the declared bit range, for narrow UI columns."""
        return f"{self.reference}{self.bit_range}"


@dataclass(slots=True)
class VCDFile:
    timescale: TimeScale
    signals: List[Signal]
    streams: Dict[str, ValueStream]
    last_time: int = 0
    warnings: List[str] = field(default_factory=list)

    def find(self, pattern: str) -> List[Signal]:
        needle = pattern.casefold()
        return [signal for signal in self.signals if needle in signal.full_name.casefold()]


@dataclass(frozen=True)
class Inspection:
    signal: Signal
    before: Optional[str]
    after: Optional[str]

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass(frozen=True)
class TreeItem:
    kind: str
    label: str
    depth: int
    path: Tuple[str, ...]
    signal_index: Optional[int] = None


@dataclass
class TUIState:
    cursor: int
    view_start: int
    view_end: int
    selected: List[bool]
    focus_pane: str = "wave"
    tree_focus: int = 0
    tree_offset: int = 0
    wave_focus: int = 0
    wave_offset: int = 0
    expanded_scopes: Set[Tuple[str, ...]] = field(default_factory=set)
    show_inspector: bool = False
    marker_a: Optional[int] = None
    marker_b: Optional[int] = None
    display_formats: List[str] = field(default_factory=list)
    status: str = ""


class TokenStream:
    """One-token lookahead over a lazy ``(token, line)`` source.

    The source is never materialized, so a trace is bounded by the value changes
    it contains rather than by the number of tokens on disk. ``line`` tracks the
    token last popped, which is what a parse error should point at.
    """

    def __init__(self, tokens: Iterable[Tuple[str, int]]) -> None:
        self._tokens = iter(tokens)
        self._pending: Optional[Tuple[str, int]] = None
        self.line = 0

    def _lookahead(self) -> Optional[Tuple[str, int]]:
        if self._pending is None:
            self._pending = next(self._tokens, None)
        return self._pending

    def peek(self) -> Optional[str]:
        """Return the next token without consuming it, or None at end of input."""
        item = self._lookahead()
        return None if item is None else item[0]

    def done(self) -> bool:
        return self._lookahead() is None

    def pop(self) -> str:
        item = self._lookahead()
        if item is None:
            raise VCDTruncatedError("unexpected end of file")
        self._pending = None
        token, self.line = item
        return token

    def collect_until_end(self) -> List[str]:
        values: List[str] = []
        while True:
            token = self.pop()
            if token == "$end":
                return values
            values.append(token)


# A UTF-8 byte order mark is not part of any token; some editors add one.
_BOM = "\ufeff"


def iter_vcd_tokens(lines: Iterable[str]) -> Iterator[Tuple[str, int]]:
    """Yield ``(token, line_number)`` pairs, one line of input at a time."""
    for number, line in enumerate(lines, start=1):
        if number == 1:
            line = line.lstrip(_BOM)
        for token in line.split():
            yield token, number


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


# $var types whose value changes do not use the bit-vector grammar. Everything
# else (wire, reg, integer, parameter, event, ...) is dumped as 0/1/x/z bits.
_REAL_VAR_TYPES = ("real", "realtime", "shortreal")
_STRING_VAR_TYPES = ("string",)


def _split_var_reference(parts: Sequence[str]) -> Tuple[str, str]:
    """Split a $var reference into its name and its declared bit range.

    IEEE 1364 allows the range to be attached to the identifier or written as
    separate tokens; the qualified baseline separates it:

        $var reg 8 " count [7:0] $end
        $var reg 3 $ \\mem[0] [2:0] $end

    Brackets that arrive in the identifier token itself are only split off when
    they are a msb:lsb range. A bare "[0]" there indexes an array element and is
    part of the name, so splitting it would merge distinct elements.
    """
    reference = parts[0]
    if len(parts) > 1:
        bit_range = "".join(parts[1:])
        if not (bit_range.startswith("[") and bit_range.endswith("]")):
            raise VCDParseError(f"invalid $var reference {' '.join(parts)!r}")
    elif (
        not reference.startswith("\\")
        and reference.endswith("]")
        and ":" in reference
        and "[" in reference
    ):
        head, _, tail = reference.rpartition("[")
        reference, bit_range = head, f"[{tail}"
    else:
        bit_range = ""
    if not reference:
        raise VCDParseError(f"invalid $var reference {' '.join(parts)!r}")
    # A leading backslash only delimits an escaped identifier; it is not part of
    # the name a user would type.
    return reference.lstrip("\\"), bit_range


def _kind_for_var_type(var_type: str) -> str:
    lowered = var_type.lower()
    if lowered in _REAL_VAR_TYPES:
        return "real"
    if lowered in _STRING_VAR_TYPES:
        return "string"
    return "bit"


def _normalize_real(value: str) -> str:
    """Validate a real value change and keep its exact textual form."""
    try:
        float(value)
    except ValueError:
        raise VCDParseError(f"invalid real value {value!r}") from None
    return value


def _normalize_vector(value: str, width: int) -> str:
    """Size a binary value to the declared width, as IEEE 1364 defines it.

    Short values are left-extended: with 0, or with x/z when the value starts
    that way. A longer value is accepted only when the excess is redundant
    extension of what remains, since nothing is then lost; an overlong value
    carrying significant bits is a real inconsistency and is rejected.
    """
    bits = value.lower()
    if not bits or any(ch not in "01xz" for ch in bits):
        raise VCDParseError(f"unsupported binary vector value {value!r}")
    if len(bits) > width:
        excess, bits = bits[: len(bits) - width], bits[len(bits) - width :]
        extension = bits[0] if bits[0] in "xz" else "0"
        if any(ch != extension for ch in excess):
            raise VCDParseError(f"vector value {value!r} exceeds declared width {width}")
    elif len(bits) < width:
        pad = bits[0] if bits[0] in "xz" else "0"
        bits = pad * (width - len(bits)) + bits
    return bits


# Extended VCD is a different format, not a dialect of this one: it records port
# direction and drive strength instead of plain value changes.
_EVCD_MESSAGE = (
    "this is an extended VCD (EVCD) file, which records port direction and "
    "strength rather than plain value changes; vcdtui reads standard VCD"
)

# Runtime dump-control directives. Each opens a block of value changes that is
# terminated by $end and carries the timestamp currently in effect.
_DUMP_CONTROL_DIRECTIVES = ("$dumpvars", "$dumpall", "$dumpoff", "$dumpon")


def _stream_for(streams: Dict[str, ValueStream], identifier: str) -> ValueStream:
    stream = streams.get(identifier)
    if stream is None:
        raise VCDParseError(f"value change for unknown identifier {identifier!r}")
    return stream


def _require_kind(stream: ValueStream, kind: str) -> None:
    if stream.kind != kind:
        raise VCDParseError(
            f"{kind} value used for {stream.identifier!r}, "
            f"declared as a {stream.kind} variable"
        )


def _adopt_kind(stream: ValueStream, kind: str) -> None:
    """Accept a real/string value on a stream whose $var type did not say so.

    Some writers declare such variables with a generic type. The value form is
    unambiguous, so adopt it rather than refusing to open the trace; only a
    stream that already carries a different value kind is an error.
    """
    if stream.kind == kind:
        return
    if stream.changes:
        _require_kind(stream, kind)
    stream.kind = kind


def _apply_value_change(
    token: str,
    ts: TokenStream,
    streams: Dict[str, ValueStream],
    time: int,
) -> None:
    """Record one value change; vector forms consume the following identifier token."""
    first = token[:1].lower()
    if first in "01xz" and len(token) > 1:
        identifier = token[1:]
        stream = _stream_for(streams, identifier)
        _require_kind(stream, "bit")
        if stream.width != 1:
            raise VCDParseError(
                f"scalar value used for {identifier!r}, declared width {stream.width}"
            )
        stream.add(time, first)
        return
    if first == "b":
        raw = token[1:]
        stream = _stream_for(streams, ts.pop())
        _require_kind(stream, "bit")
        stream.add(time, _normalize_vector(raw, stream.width))
        return
    if first == "r":
        raw = token[1:]
        stream = _stream_for(streams, ts.pop())
        _adopt_kind(stream, "real")
        stream.add(time, _normalize_real(raw))
        return
    if first == "s":
        # A string value may legitimately be empty, so "s" alone is valid.
        raw = token[1:]
        stream = _stream_for(streams, ts.pop())
        _adopt_kind(stream, "string")
        stream.add(time, raw)
        return
    if ts.done():
        # A trace cut mid-token leaves a fragment such as a lone "0" or "b101".
        raise VCDTruncatedError(f"unexpected end of file after {token!r}")
    raise VCDParseError(f"unsupported value-change token {token!r}")


def _parse_value_change_step(
    ts: TokenStream,
    streams: Dict[str, ValueStream],
    current_time: int,
    last_time: int,
) -> Tuple[int, int]:
    """Consume one value-change item and return the updated (current, last) time."""
    token = ts.pop()
    if token == "$comment":
        ts.collect_until_end()
        return current_time, last_time
    if token in _DUMP_CONTROL_DIRECTIVES:
        _parse_dump_block(token, ts, streams, current_time)
        return current_time, last_time
    if token == "$end":
        raise VCDParseError("$end without a matching dump-control directive")
    if token.startswith("$dumpports"):
        raise VCDParseError(_EVCD_MESSAGE)
    if token.startswith("$"):
        raise VCDParseError(f"unsupported value-change directive {token}")
    if token.startswith("#"):
        stamp = token[1:]
        if not stamp.isdigit():
            raise VCDParseError(f"invalid timestamp {token!r}")
        new_time = int(stamp)
        if new_time < current_time:
            raise VCDParseError("timestamps must be nondecreasing")
        return new_time, max(last_time, new_time)
    _apply_value_change(token, ts, streams, current_time)
    return current_time, last_time


def _parse_dump_block(
    directive: str,
    ts: TokenStream,
    streams: Dict[str, ValueStream],
    time: int,
) -> None:
    """Parse ``$dumpvars``/``$dumpall``/``$dumpoff``/``$dumpon`` up to its ``$end``.

    The block body uses exactly the same value-change grammar as the surrounding
    stream, so the recorded values are part of the trace rather than skipped.
    """
    while True:
        if ts.done():
            raise VCDTruncatedError(f"unterminated {directive}")
        token = ts.pop()
        if token == "$end":
            return
        if token.startswith("#"):
            raise VCDParseError(f"timestamp {token!r} inside {directive} block")
        if token == "$comment":
            ts.collect_until_end()
            continue
        if token.startswith("$"):
            raise VCDParseError(f"unsupported directive {token} inside {directive} block")
        _apply_value_change(token, ts, streams, time)


def parse_vcd_text(text: str) -> VCDFile:
    """Parse a whole VCD held in memory. Prefer ``parse_vcd`` for files."""
    return _parse_tokens(TokenStream(iter_vcd_tokens(text.splitlines())))


def _parse_tokens(ts: TokenStream) -> VCDFile:
    try:
        return _parse_vcd(ts)
    except VCDParseError as exc:
        raise VCDParseError(f"line {ts.line}: {exc}") from None


def _reject_non_vcd_input(ts: TokenStream) -> None:
    """Fail early and legibly when the input is not a VCD at all."""
    token = ts.peek()
    if token is None:
        raise VCDParseError("file is empty")
    if not token.startswith("$"):
        raise VCDParseError(
            f"does not look like a VCD file: expected a $ directive, found {token!r}"
        )


def _parse_vcd(ts: TokenStream) -> VCDFile:
    _reject_non_vcd_input(ts)
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
            if var_type.lower() == "port":
                raise VCDParseError(_EVCD_MESSAGE)
            if not width_text.isdigit() or int(width_text) <= 0:
                raise VCDParseError(f"invalid width in $var: {width_text!r}")
            width = int(width_text)
            reference, bit_range = _split_var_reference(parts[3:])
            kind = _kind_for_var_type(var_type)
            stream = streams.get(identifier)
            if stream is None:
                stream = ValueStream(identifier=identifier, width=width, kind=kind)
                streams[identifier] = stream
            elif stream.width != width:
                raise VCDParseError(
                    f"identifier {identifier!r} is declared with incompatible widths "
                    f"{stream.width} and {width}"
                )
            elif stream.kind != kind:
                raise VCDParseError(
                    f"identifier {identifier!r} is declared with incompatible value kinds "
                    f"{stream.kind} and {kind}"
                )
            full_name = ".".join(scopes + [reference]) if scopes else reference
            signals.append(Signal(full_name, reference, width, var_type, stream, bit_range))
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
    warnings: List[str] = []

    while not ts.done():
        try:
            current_time, last_time = _parse_value_change_step(
                ts, streams, current_time, last_time
            )
        except VCDTruncatedError as exc:
            # A writer killed mid-trace leaves a complete header and value
            # changes that simply stop. Everything already recorded is still
            # true, so keep it and say so instead of discarding the whole file.
            warnings.append(f"trace is truncated at line {ts.line}: {exc}")
            break

    return VCDFile(
        timescale=timescale,
        signals=signals,
        streams=streams,
        last_time=last_time,
        warnings=warnings,
    )


def parse_vcd(path: Path) -> VCDFile:
    """Parse a VCD file, streaming it line by line.

    Decoding is deliberately forgiving: a stray non-UTF-8 byte in a $comment or
    a $date must not make a whole trace unreadable, and only tokens matter.
    """
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            return _parse_tokens(TokenStream(iter_vcd_tokens(handle)))
    except VCDParseError as exc:
        raise VCDParseError(f"{path}: {exc}") from None
    except OSError as exc:
        raise VCDTUIError(f"cannot read {path}: {exc.strerror or exc}") from exc


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
        "--scope",
        metavar="PATH",
        help="resolve selectors inside PATH and name signals relative to it",
    )
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


def scope_paths(vcd: VCDFile) -> List[str]:
    """Every scope path in the trace, in declaration order and without repeats.

    Derived from the signal names rather than recorded during parsing, so a
    scope that declares nothing does not show up as a place to look.
    """
    paths: Dict[str, None] = {}
    for signal in vcd.signals:
        scopes = signal.full_name.split(".")[:-1]
        for depth in range(1, len(scopes) + 1):
            paths.setdefault(".".join(scopes[:depth]), None)
    return list(paths)


def resolve_scope(vcd: VCDFile, selector: str) -> str:
    """Expand a --scope selector to one full scope path.

    Accepts the same forms as a signal selector, except that ambiguity is fatal:
    a view can only be rooted at one place, so guessing would silently show the
    wrong instance.
    """
    needle = selector.strip().casefold()
    if not needle:
        raise VCDTUIError("--scope requires a scope path")
    paths = scope_paths(vcd)
    for path in paths:
        if path.casefold() == needle:
            return path
    matches = [path for path in paths if _matches_path(path.casefold(), needle)]
    if not matches:
        raise VCDTUIError(
            f"scope {selector!r} was not found; run --list to see the hierarchy"
        )
    if len(matches) > 1:
        listing = "".join(f"\n  {path}" for path in matches[:_MAX_REPORTED_MATCHES])
        raise VCDTUIError(
            f"scope {selector!r} matched {len(matches)} scopes; "
            f"use a longer path:{listing}"
        )
    return matches[0]


def scoped_view(vcd: VCDFile, selector: str) -> VCDFile:
    """Restrict the trace to one scope and re-root the names it contains.

    Everything downstream - selection, --list, --find, --dump, the tree - reads
    ``full_name``, so re-rooting once here is what keeps the shorter names
    consistent across all of them. Streams are shared, not copied: the view is a
    renaming, not a second parse.
    """
    root = resolve_scope(vcd, selector)
    prefix = f"{root}."
    signals = [
        replace(signal, full_name=signal.full_name[len(prefix):])
        for signal in vcd.signals
        if signal.full_name.startswith(prefix)
    ]
    return VCDFile(
        timescale=vcd.timescale,
        signals=signals,
        streams=vcd.streams,
        last_time=vcd.last_time,
        warnings=list(vcd.warnings),
    )


def _matches_path(name: str, needle: str) -> bool:
    """True when ``needle`` is the whole name or a trailing run of its scopes.

    Anchoring at "." is what makes "dut4.clk" mean the clk inside dut4 while
    "ut4.clk" means nothing.
    """
    return name == needle or name.endswith("." + needle)


# An ambiguous selector is legitimate - every clock in the design is a
# reasonable thing to ask for - but it is rarely what was meant, so name the
# paths that would have narrowed it. Beyond this many, print a count instead.
_MAX_REPORTED_MATCHES = 8


def _describe_ambiguity(selector: str, matched: Sequence[Signal]) -> str:
    names = [signal.full_name for signal in matched]
    if len(names) > _MAX_REPORTED_MATCHES:
        shown = names[:_MAX_REPORTED_MATCHES]
        tail = f"\n  ... and {len(names) - _MAX_REPORTED_MATCHES} more; run --list for all of them"
    else:
        shown, tail = names, ""
    listing = "".join(f"\n  {name}" for name in shown)
    return (
        f"{selector!r} matched {len(names)} signals; "
        f"select one with its path:{listing}{tail}"
    )


def select_signals(
    vcd: VCDFile,
    selectors: Optional[str],
    *,
    warnings: Optional[List[str]] = None,
) -> List[Signal]:
    """Resolve --signals selectors, in declaration order and without duplicates.

    Selectors are resolved in tiers, narrowest first: a signal's whole name, then
    a trailing run of its scopes, then a substring. A precise name is therefore
    never widened - "clk" means the top-level clk when one exists, and every clk
    in the design only when it does not.
    """
    if selectors is None:
        if not vcd.signals:
            raise VCDTUIError("trace contains no signals")
        return list(vcd.signals)

    requested = [part.strip() for part in selectors.split(",")]
    if not requested or any(not part for part in requested):
        raise VCDTUIError("--signals requires non-empty comma-separated selectors")

    selected_indexes: Set[int] = set()
    for selector in requested:
        needle = selector.casefold()
        matches = [
            index
            for index, signal in enumerate(vcd.signals)
            if needle in (signal.full_name.casefold(), signal.display_name.casefold())
        ]
        if not matches:
            matches = [
                index
                for index, signal in enumerate(vcd.signals)
                if _matches_path(signal.full_name.casefold(), needle)
                or _matches_path(signal.display_name.casefold(), needle)
            ]
        if not matches:
            matches = [
                index
                for index, signal in enumerate(vcd.signals)
                if needle in signal.full_name.casefold()
            ]
        if not matches:
            raise VCDTUIError(f"requested signal {selector!r} was not found")
        if warnings is not None and len(matches) > 1:
            warnings.append(
                _describe_ambiguity(selector, [vcd.signals[index] for index in matches])
            )
        selected_indexes.update(matches)

    return [signal for index, signal in enumerate(vcd.signals) if index in selected_indexes]


def resolve_range(vcd: VCDFile, start_text: Optional[str], end_text: Optional[str]) -> Tuple[int, int]:
    start = vcd.timescale.parse_ticks(start_text) if start_text is not None else 0
    end = vcd.timescale.parse_ticks(end_text) if end_text is not None else vcd.last_time
    if start > end:
        raise VCDTUIError(f"invalid time range: start tick {start} is after end tick {end}")
    final = f"{vcd.last_time} ({vcd.timescale.format_tick(vcd.last_time)})"
    if start > vcd.last_time:
        raise VCDTUIError(
            f"range starts at tick {start}, beyond the final VCD timestamp {final}"
        )
    if end > vcd.last_time:
        raise VCDTUIError(
            f"range ends at tick {end}, beyond the final VCD timestamp {final}"
        )
    return start, end


def inspect_at(signals: Sequence[Signal], cursor: int) -> List[Inspection]:
    return [
        Inspection(
            signal=signal,
            before=signal.stream.value_before(cursor),
            after=signal.stream.value_at(cursor),
        )
        for signal in signals
    ]


_DISPLAY_FORMATS = ("binary", "hex", "unsigned", "signed")


def format_signal_value(signal: Signal, value: Optional[str], display_format: str = "binary") -> str:
    """Format one VCD value for presentation without changing the stored trace value."""
    if value is None:
        return "?"
    if signal.stream.kind != "bit":
        return value
    text = value.lower()
    if signal.width <= 1 or text == "?":
        return text
    if display_format not in _DISPLAY_FORMATS:
        raise ValueError(f"unknown display format {display_format!r}")
    if any(ch in text for ch in "xz?"):
        return text
    if display_format == "binary":
        return text
    number = int(text, 2)
    if display_format == "hex":
        digits = max(1, (signal.width + 3) // 4)
        return f"0x{number:0{digits}X}"
    if display_format == "unsigned":
        return str(number)
    sign_bit = 1 << (signal.width - 1)
    signed = number - (1 << signal.width) if number & sign_bit else number
    return str(signed)


def next_transition(stream: ValueStream, cursor: int, *, forward: bool) -> Optional[int]:
    if forward:
        index = bisect_right(stream.changes, cursor, key=lambda change: change.time)
        if index >= len(stream.changes):
            return None
        return stream.changes[index].time
    index = bisect_left(stream.changes, cursor, key=lambda change: change.time) - 1
    if index < 0:
        return None
    return stream.changes[index].time


def edge_times(stream: ValueStream, kind: str) -> List[int]:
    if stream.width != 1 or stream.kind != "bit":
        return []
    if kind not in ("rising", "falling", "any"):
        raise ValueError(f"unknown edge kind {kind!r}")
    result: List[int] = []
    previous: Optional[str] = None
    for change in stream.changes:
        current = change.value
        rising = previous == "0" and current == "1"
        falling = previous == "1" and current == "0"
        if (kind == "rising" and rising) or (kind == "falling" and falling):
            result.append(change.time)
        elif kind == "any" and (rising or falling):
            result.append(change.time)
        previous = current
    return result


def next_edge(stream: ValueStream, cursor: int, kind: str, *, forward: bool) -> Optional[int]:
    times = edge_times(stream, kind)
    if forward:
        index = bisect_right(times, cursor)
        return None if index >= len(times) else times[index]
    index = bisect_left(times, cursor) - 1
    return None if index < 0 else times[index]


def pan_window(
    view_start: int,
    view_end: int,
    range_start: int,
    range_end: int,
    *,
    forward: bool,
) -> Tuple[int, int]:
    if range_start >= range_end or view_start >= view_end:
        return view_start, view_end
    span = view_end - view_start
    step = max(1, span // 4)
    if forward:
        new_end = min(range_end, view_end + step)
        new_start = new_end - span
        if new_start < range_start:
            new_start = range_start
            new_end = min(range_end, new_start + span)
        return new_start, new_end
    new_start = max(range_start, view_start - step)
    new_end = new_start + span
    if new_end > range_end:
        new_end = range_end
        new_start = max(range_start, new_end - span)
    return new_start, new_end


def zoom_window(
    view_start: int,
    view_end: int,
    cursor: int,
    range_start: int,
    range_end: int,
    *,
    zoom_in: bool,
) -> Tuple[int, int]:
    full_span = range_end - range_start
    if full_span <= 0:
        return range_start, range_end
    span = max(1, view_end - view_start)
    if zoom_in:
        new_span = max(1, span // 2)
    else:
        new_span = min(full_span, max(span + 1, span * 2))
    if new_span >= full_span:
        return range_start, range_end
    center = cursor if view_start <= cursor <= view_end else (view_start + view_end) // 2
    new_start = center - new_span // 2
    new_end = new_start + new_span
    if new_start < range_start:
        new_start = range_start
        new_end = new_start + new_span
    if new_end > range_end:
        new_end = range_end
        new_start = new_end - new_span
    return new_start, new_end


def recenter_window(
    view_start: int,
    view_end: int,
    cursor: int,
    range_start: int,
    range_end: int,
) -> Tuple[int, int]:
    if view_start <= cursor <= view_end:
        return view_start, view_end
    full_span = range_end - range_start
    span = min(max(1, view_end - view_start), max(1, full_span))
    if full_span <= 0:
        return range_start, range_end
    new_start = cursor - span // 2
    new_end = new_start + span
    if new_start < range_start:
        new_start = range_start
        new_end = min(range_end, new_start + span)
    if new_end > range_end:
        new_end = range_end
        new_start = max(range_start, new_end - span)
    return new_start, new_end


def selected_signals(all_signals: Sequence[Signal], selected: Sequence[bool]) -> List[Signal]:
    return [signal for signal, enabled in zip(all_signals, selected) if enabled]


def _initial_selection(all_signals: Sequence[Signal], initial: Sequence[Signal]) -> List[bool]:
    chosen = {id(signal) for signal in initial}
    return [id(signal) in chosen for signal in all_signals]


def _signal_scope(signal: Signal) -> Tuple[str, ...]:
    suffix = "." + signal.reference
    if signal.full_name.endswith(suffix):
        prefix = signal.full_name[: -len(suffix)]
        return tuple(part for part in prefix.split(".") if part)
    return ()


def all_scope_paths(signals: Sequence[Signal]) -> Set[Tuple[str, ...]]:
    paths: Set[Tuple[str, ...]] = set()
    for signal in signals:
        scope = _signal_scope(signal)
        for depth in range(1, len(scope) + 1):
            paths.add(scope[:depth])
    return paths


def build_tree_items(
    signals: Sequence[Signal],
    expanded_scopes: Set[Tuple[str, ...]],
) -> List[TreeItem]:
    children: Dict[Tuple[str, ...], List[str]] = {}
    members: Dict[Tuple[str, ...], List[int]] = {}

    for index, signal in enumerate(signals):
        scope = _signal_scope(signal)
        parent: Tuple[str, ...] = ()
        for component in scope:
            bucket = children.setdefault(parent, [])
            if component not in bucket:
                bucket.append(component)
            parent = parent + (component,)
        members.setdefault(parent, []).append(index)

    items: List[TreeItem] = []

    def visit(parent: Tuple[str, ...], depth: int) -> None:
        for component in children.get(parent, []):
            path = parent + (component,)
            items.append(TreeItem("scope", component, depth, path))
            if path in expanded_scopes:
                visit(path, depth + 1)
        for index in members.get(parent, []):
            signal = signals[index]
            items.append(TreeItem("signal", signal.display_reference, depth, parent, index))

    visit((), 0)
    return items


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
    headers = ["tick", "time"] + [signal.display_name for signal in signals]
    rows: List[List[str]] = []
    for tick in _event_times(signals, start, end):
        values = [signal.stream.value_at(tick) or "?" for signal in signals]
        rows.append([str(tick), vcd.timescale.format_tick(tick)] + values)
    return headers, rows


def _color_value(signal: Signal, value: str, enabled: bool) -> str:
    if not enabled or value == "?":
        return value
    if signal.stream.kind != "bit":
        color = "36"
    elif "x" in value:
        color = "31"
    elif "z" in value:
        color = "35"
    elif signal.width == 1:
        color = "32"
    else:
        color = "36"
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


def _sample_ticks(start: int, end: int, width: int) -> List[int]:
    if width <= 0:
        return []
    if width == 1 or start == end:
        return [start] * width
    span = end - start
    return [start + (span * index) // (width - 1) for index in range(width)]


def sample_waveform(
    signal: Signal,
    start: int,
    end: int,
    width: int,
    *,
    ascii_only: bool,
) -> str:
    """Legacy compact state sampling kept for deterministic tests/API compatibility."""
    ticks = _sample_ticks(start, end, width)
    output: List[str] = []
    for tick in ticks:
        value = signal.stream.value_at(tick)
        if value is None:
            char = "?"
        elif signal.stream.kind != "bit":
            char = "="
        elif "x" in value:
            char = "x"
        elif "z" in value:
            char = "z"
        elif signal.width > 1:
            char = "="
        elif value == "1":
            char = "-" if ascii_only else "‾"
        else:
            char = "_"
        output.append(char)
    return "".join(output)


def render_scalar_track(
    signal: Signal,
    start: int,
    end: int,
    width: int,
    *,
    ascii_only: bool,
) -> str:
    ticks = _sample_ticks(start, end, width)
    output: List[str] = []
    previous: Optional[str] = None
    for tick in ticks:
        value = signal.stream.value_at(tick)
        if previous == "0" and value == "1":
            char = "/"
        elif previous == "1" and value == "0":
            char = "\\"
        elif value is None:
            char = "?"
        elif "x" in value:
            char = "x"
        elif "z" in value:
            char = "z"
        elif value == "1":
            char = "-" if ascii_only else "‾"
        else:
            char = "_"
        output.append(char)
        previous = value
    return "".join(output)


def render_bus_track(
    signal: Signal,
    start: int,
    end: int,
    width: int,
    *,
    ascii_only: bool,
    display_format: str = "binary",
) -> str:
    if width <= 0:
        return ""
    ticks = _sample_ticks(start, end, width)
    raw_values = [signal.stream.value_at(tick) or "?" for tick in ticks]
    horizontal = "-" if ascii_only else "─"
    boundary = "|" if ascii_only else "│"
    line = [horizontal] * width

    run_start = 0
    while run_start < width:
        raw_value = raw_values[run_start]
        run_end = run_start + 1
        while run_end < width and raw_values[run_end] == raw_value:
            run_end += 1
        if run_start > 0:
            line[run_start] = boundary
        content_start = run_start + (1 if run_start > 0 else 0)
        available = max(0, run_end - content_start)
        if available > 0:
            label = format_signal_value(signal, raw_value, display_format)[:available]
            label_start = content_start + max(0, (available - len(label)) // 2)
            for offset, char in enumerate(label):
                if label_start + offset < run_end:
                    line[label_start + offset] = char
        run_start = run_end
    return "".join(line)


def render_waveform_track(
    signal: Signal,
    start: int,
    end: int,
    width: int,
    *,
    ascii_only: bool,
    display_format: str = "binary",
) -> str:
    if signal.width == 1 and signal.stream.kind == "bit":
        return render_scalar_track(signal, start, end, width, ascii_only=ascii_only)
    return render_bus_track(
        signal, start, end, width, ascii_only=ascii_only, display_format=display_format
    )


def _cursor_column(cursor: int, start: int, end: int, width: int) -> int:
    if width <= 1 or start == end:
        return 0
    return min(width - 1, max(0, ((cursor - start) * (width - 1)) // (end - start)))


def cursor_track_glyph(track: str, column: int) -> str:
    """Return the original track glyph under the cursor; the UI only changes attributes."""
    if not track:
        return " "
    return track[min(max(0, column), len(track) - 1)]


def _safe_addstr(window, y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = window.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    available = max(0, width - x - 1)
    if available <= 0:
        return
    try:
        window.addstr(y, x, text[:available], attr)
    except Exception:
        pass


def _prompt_goto(stdscr, vcd: VCDFile, start: int, end: int, status_row: int) -> Tuple[Optional[int], str]:
    import curses

    height, width = stdscr.getmaxyx()
    if status_row >= height:
        return None, "terminal too small for goto prompt"
    prompt = "goto time/tick: "
    stdscr.move(status_row, 0)
    stdscr.clrtoeol()
    _safe_addstr(stdscr, status_row, 0, prompt)
    stdscr.refresh()
    curses.echo()
    try:
        raw = stdscr.getstr(
            status_row,
            min(len(prompt), max(0, width - 2)),
            max(1, width - len(prompt) - 2),
        )
    finally:
        curses.noecho()
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeError:
        return None, "goto input is not valid UTF-8"
    if not text:
        return None, "goto cancelled"
    try:
        tick = vcd.timescale.parse_ticks(text)
    except VCDTUIError as exc:
        return None, str(exc)
    if not start <= tick <= end:
        return None, f"tick {tick} is outside the active range {start}..{end}"
    return tick, ""


def _init_curses_colors(curses, enabled: bool) -> Dict[str, int]:
    attrs = {
        "scalar": 0,
        "vector": 0,
        "bad": 0,
        "cursor": curses.A_REVERSE | curses.A_BOLD,
        "dim": curses.A_DIM,
        "focus": curses.A_REVERSE,
        "scope": curses.A_BOLD,
        "marker_a": curses.A_UNDERLINE | curses.A_BOLD,
        "marker_b": curses.A_BOLD,
    }
    if not enabled or not curses.has_colors():
        return attrs
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_YELLOW, -1)
        curses.init_pair(5, curses.COLOR_CYAN, -1)
        curses.init_pair(6, curses.COLOR_MAGENTA, -1)
        attrs.update(
            scalar=curses.color_pair(1),
            vector=curses.color_pair(2),
            bad=curses.color_pair(3),
            cursor=curses.color_pair(4) | curses.A_REVERSE | curses.A_BOLD,
            scope=curses.color_pair(2) | curses.A_BOLD,
            marker_a=curses.color_pair(5) | curses.A_UNDERLINE | curses.A_BOLD,
            marker_b=curses.color_pair(6) | curses.A_BOLD,
        )
    except curses.error:
        pass
    return attrs


def _ensure_offset(focus: int, offset: int, capacity: int, count: int) -> Tuple[int, int]:
    if count <= 0:
        return 0, 0
    focus = min(max(0, focus), count - 1)
    if capacity <= 0:
        return focus, focus
    if focus < offset:
        offset = focus
    elif focus >= offset + capacity:
        offset = focus - capacity + 1
    offset = min(max(0, offset), max(0, count - capacity))
    return focus, offset


def _visible_signal_indexes(state: TUIState) -> List[int]:
    return [index for index, enabled in enumerate(state.selected) if enabled]


def marker_values(
    signals: Sequence[Signal],
    tick: int,
    display_formats: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return post-change values at a marker tick for the supplied signals."""
    formats = list(display_formats) if display_formats is not None else ["binary"] * len(signals)
    return [
        format_signal_value(
            signal,
            signal.stream.value_at(tick),
            formats[index] if index < len(formats) else "binary",
        )
        for index, signal in enumerate(signals)
    ]


def marker_delta_ticks(marker_a: Optional[int], marker_b: Optional[int]) -> Optional[int]:
    """Return signed B-A in raw VCD ticks when both markers exist."""
    if marker_a is None or marker_b is None:
        return None
    return marker_b - marker_a


def marker_table_lines(
    vcd: VCDFile,
    signals: Sequence[Signal],
    marker_a: Optional[int],
    marker_b: Optional[int],
    width: int,
    *,
    ascii_only: bool,
    display_formats: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build a compact marker table using the currently displayed signals."""
    if marker_a is None and marker_b is None:
        return []

    sep = " | " if ascii_only else " │ "
    fixed_headers = ["marker", "tick", "time"]
    fixed_widths = [6, 8, 10]
    used = sum(fixed_widths) + len(sep) * (len(fixed_widths) - 1)

    formats = list(display_formats) if display_formats is not None else ["binary"] * len(signals)
    chosen: List[Signal] = []
    chosen_formats: List[str] = []
    signal_widths: List[int] = []
    for signal_index, signal in enumerate(signals):
        display_format = formats[signal_index] if signal_index < len(formats) else "binary"
        values = []
        if marker_a is not None:
            values.append(format_signal_value(signal, signal.stream.value_at(marker_a), display_format))
        if marker_b is not None:
            values.append(format_signal_value(signal, signal.stream.value_at(marker_b), display_format))
        col_width = min(
            14, max(3, len(signal.display_reference), *(len(value) for value in values))
        )
        extra = len(sep) + col_width
        if used + extra > max(1, width):
            break
        chosen.append(signal)
        chosen_formats.append(display_format)
        signal_widths.append(col_width)
        used += extra

    headers = fixed_headers + [signal.display_reference for signal in chosen]
    widths = fixed_widths + signal_widths

    def format_row(cells: Sequence[str]) -> str:
        parts: List[str] = []
        for index, cell in enumerate(cells):
            text = cell
            if len(text) > widths[index]:
                text = text[: max(1, widths[index] - 1)] + ("~" if ascii_only else "…")
            parts.append(text.ljust(widths[index]))
        return sep.join(parts).rstrip()

    def marker_row(label: str, tick: Optional[int]) -> List[str]:
        if tick is None:
            return [label, "-", "-"] + ["-" for _ in chosen]
        return [
            label,
            str(tick),
            vcd.timescale.format_tick(tick),
            *marker_values(chosen, tick, chosen_formats),
        ]

    lines = [format_row(headers), format_row(marker_row("A", marker_a)), format_row(marker_row("B", marker_b))]
    delta = marker_delta_ticks(marker_a, marker_b)
    if delta is None:
        delta_row = ["delta", "-", "-"] + ["" for _ in chosen]
    else:
        delta_row = ["delta", str(delta), vcd.timescale.format_tick(delta)] + ["" for _ in chosen]
    lines.append(format_row(delta_row))
    return lines


def nice_timeline_step(start: int, end: int, width: int, *, min_columns: int = 12) -> int:
    """Choose a deterministic 1/2/5 x 10^n major-tick spacing in raw VCD ticks."""
    if end <= start or width <= 1:
        return 1
    span = end - start
    denominator = max(1, width - 1)
    desired = max(1, (span * max(1, min_columns) + denominator - 1) // denominator)
    magnitude = 1
    while desired > 10 * magnitude:
        magnitude *= 10
    for factor in (1, 2, 5, 10):
        step = factor * magnitude
        if step >= desired:
            return step
    return 10 * magnitude


def _timeline_minor_step(major_step: int) -> Optional[int]:
    if major_step <= 1:
        return None
    if major_step % 5 == 0:
        return major_step // 5
    if major_step % 2 == 0:
        return major_step // 2
    return 1


def _ticks_on_grid(start: int, end: int, step: int) -> List[int]:
    if step <= 0 or end < start:
        return []
    first = ((start + step - 1) // step) * step
    return list(range(first, end + 1, step))


def render_timeline_ruler(
    timescale: TimeScale,
    start: int,
    end: int,
    width: int,
    *,
    ascii_only: bool,
) -> Tuple[str, str]:
    """Return label and rule rows for an exact, terminal-width-independent time ruler."""
    if width <= 0:
        return "", ""
    if width == 1:
        return timescale.format_tick(start)[:1], "|" if ascii_only else "┼"

    horizontal = "-" if ascii_only else "─"
    major_glyph = "|" if ascii_only else "┼"
    minor_glyph = "." if ascii_only else "┊"
    labels = [" "] * width
    rule = [horizontal] * width

    major_step = nice_timeline_step(start, end, width)
    minor_step = _timeline_minor_step(major_step)
    if minor_step is not None:
        for tick in _ticks_on_grid(start, end, minor_step):
            col = _cursor_column(tick, start, end, width)
            rule[col] = minor_glyph
    major_ticks = _ticks_on_grid(start, end, major_step)
    for tick in major_ticks:
        col = _cursor_column(tick, start, end, width)
        rule[col] = major_glyph
    rule[0] = major_glyph
    rule[-1] = major_glyph

    occupied = [False] * width

    def place(text: str, left: int) -> None:
        if not text:
            return
        left = min(max(0, left), max(0, width - len(text)))
        right = min(width, left + len(text))
        if any(occupied[left:right]):
            return
        for offset, char in enumerate(text[: width - left]):
            labels[left + offset] = char
            occupied[left + offset] = True

    start_label = timescale.format_tick(start)
    end_label = timescale.format_tick(end)
    place(start_label, 0)
    place(end_label, max(0, width - len(end_label)))

    for tick in major_ticks:
        if tick in (start, end):
            continue
        text = timescale.format_tick(tick)
        col = _cursor_column(tick, start, end, width)
        left = col - len(text) // 2
        place(text, left)

    return "".join(labels), "".join(rule)


# Ctrl+A arrives as the raw control code, not as a named curses key.
_CTRL_A = 1


def _ctrl_horizontal_direction(curses_module, key: int) -> Optional[bool]:
    """Return False/True for Ctrl+Left/Ctrl+Right when terminfo exposes them."""
    try:
        name = curses_module.keyname(key)
    except Exception:
        return None
    if isinstance(name, bytes):
        try:
            name = name.decode("ascii")
        except UnicodeError:
            return None
    if name in ("kLFT5", "KEY_CLEFT", "CTRL_LEFT"):
        return False
    if name in ("kRIT5", "KEY_CRIGHT", "CTRL_RIGHT"):
        return True
    return None


def _range_boundary_for_key(
    curses_module,
    key: int,
    start: int,
    end: int,
) -> Optional[int]:
    home = getattr(curses_module, "KEY_HOME", None)
    finish = getattr(curses_module, "KEY_END", None)
    if key == ord("0") or (home is not None and key == home):
        return start
    if key == ord("$") or (finish is not None and key == finish):
        return end
    return None


def _help_lines(*, ascii_only: bool) -> List[str]:
    arrows = "<-/->" if ascii_only else "←/→"
    ctrl_arrows = "Ctrl+<-/->" if ascii_only else "Ctrl+←/→"
    return [
        "vcdtui controls",
        "Signals",
        "  Tab                 switch signal-tree / waveform focus",
        "  Up/Down, j/k        move within the focused pane",
        "  Enter               expand / collapse the focused scope",
        "  Space               show/hide the focused signal, or a whole scope",
        "  a / Ctrl+A          show all signals, or hide all when all are shown",
        "  A                   hide all signals",
        "  v                   value format menu (Up/Down, Enter, Esc)",
        "Time & view",
        f"  {arrows:<20} cursor one VCD tick",
        f"  {ctrl_arrows:<20} previous / next clean binary edge",
        "  Home / End          active-range start / end",
        "  g                   goto exact tick or physical time",
        "  < / >   + / -       pan / zoom viewport",
        "  n/N  e/E  r/R  f/F transition / edge / rising / falling",
        "Inspect",
        "  i                   before/after inspector",
        "  m / M               place marker A / B",
        "  c                   clear markers",
        "F1 / ?  close help                                      q  quit",
    ]


def _centered_panel_geometry(
    height: int,
    width: int,
    content_width: int,
    content_height: int,
) -> Tuple[int, int, int, int]:
    panel_width = min(max(24, content_width + 4), max(1, width))
    panel_height = min(max(4, content_height + 2), max(1, height))
    top = max(0, (height - panel_height) // 2)
    left = max(0, (width - panel_width) // 2)
    return top, left, panel_height, panel_width


def _is_help_key(curses_module, key: int) -> bool:
    f1 = getattr(curses_module, "KEY_F1", None)
    return key == ord("?") or (f1 is not None and key == f1)


def shortcut_bar(width: int, *, ascii_only: bool) -> str:
    if width <= 0:
        return ""
    sep = " | " if ascii_only else " · "
    arrows = "<- -> cursor" if ascii_only else "←→ cursor"
    ctrl_edges = "Ctrl<- -> edge" if ascii_only else "Ctrl+←→ edge"
    candidates = [
        ["Tab pane", "Space show/hide", "a all", "v format", arrows, ctrl_edges, "+/- zoom", "m/M markers", "F1/? help", "q quit"],
        ["Tab pane", "Space show/hide", "v format", arrows, "+/- zoom", "F1/? help", "q quit"],
        ["Tab pane", arrows, "+/- zoom", "F1/? help", "q quit"],
        [arrows, "F1/? help", "q quit"],
        ["F1/? help", "q quit"],
    ]
    for items in candidates:
        rendered = sep.join(items)
        if len(rendered) <= width:
            return rendered
    return "?"[:width]


VALUE_FORMAT_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("binary", "binary"),
    ("hex", "hexadecimal"),
    ("unsigned", "unsigned decimal"),
    ("signed", "signed decimal (two's complement)"),
)

# Row offset of the first choice in the menu, past the title and its blank line.
_VALUE_FORMAT_FIRST_ROW = 2


def signal_indexes_in_scope(
    signals: Sequence[Signal],
    path: Tuple[str, ...],
) -> List[int]:
    """Indexes of every signal at or below a scope path.

    Matching is per scope component, so the scope "dut" does not collect the
    signals of "dut4" and "dut8".
    """
    return [
        index
        for index, signal in enumerate(signals)
        if _signal_scope(signal)[: len(path)] == path
    ]


def toggle_scope_selection(selected: Sequence[bool], indexes: Sequence[int]) -> List[bool]:
    """Show a whole group, or hide it when every signal in it is already shown."""
    updated = list(selected)
    if not indexes:
        return updated
    target = not all(updated[index] for index in indexes)
    for index in indexes:
        updated[index] = target
    return updated


def toggle_all_selection(selected: Sequence[bool]) -> List[bool]:
    """Show every signal, or hide them all when every one is already shown."""
    return [not all(selected)] * len(selected)


def move_menu_index(index: int, count: int, delta: int) -> int:
    """Move a menu cursor by ``delta``, wrapping at both ends."""
    if count <= 0:
        return 0
    return (index + delta) % count


def value_format_index(current: str) -> int:
    """Menu row for the format in use, or the first row when it is unknown."""
    for index, (name, _) in enumerate(VALUE_FORMAT_CHOICES):
        if name == current:
            return index
    return 0


def value_format_menu_lines(
    signal: Signal,
    current: str,
    highlighted: int,
    *,
    ascii_only: bool,
) -> List[str]:
    """Render the value-format menu: a cursor to move, and the format in use."""
    pointer = ">" if ascii_only else "\u25b8"
    lines = [f"value format: {signal.display_reference}", ""]
    for index, (name, label) in enumerate(VALUE_FORMAT_CHOICES):
        cursor = pointer if index == highlighted else " "
        active = "*" if name == current else " "
        lines.append(f" {cursor} {active} {label}")
    up_down = "Up/Down" if ascii_only else "\u2191/\u2193"
    lines.extend(["", f" {up_down} choose   Enter apply   Esc cancel"])
    return lines


def _prompt_value_format(stdscr, signal: Signal, current: str) -> Optional[str]:
    """Prompt for one vector signal's presentation radix.

    The cursor starts on the format in use, so Enter alone is a no-op rather
    than a surprise.
    """
    import curses

    ascii_only = not _panel_supports_unicode()
    highlighted = value_format_index(current)
    while True:
        lines = value_format_menu_lines(signal, current, highlighted, ascii_only=ascii_only)
        height, width = stdscr.getmaxyx()
        content_width = max(len(line) for line in lines)
        top, left, panel_height, panel_width = _centered_panel_geometry(
            height, width, content_width, len(lines)
        )
        try:
            panel = curses.newwin(panel_height, panel_width, top, left)
            panel.keypad(True)
            panel.erase()
            panel.box()
            for row, line in enumerate(lines[: max(0, panel_height - 2)], start=1):
                if row == 1:
                    attr = curses.A_BOLD
                elif row - 1 == _VALUE_FORMAT_FIRST_ROW + highlighted:
                    attr = curses.A_REVERSE
                else:
                    attr = 0
                _safe_addstr(panel, row, 2, line, attr)
            panel.refresh()
            key = panel.getch()
        except curses.error:
            return None

        if key in (curses.KEY_UP, ord("k")):
            highlighted = move_menu_index(highlighted, len(VALUE_FORMAT_CHOICES), -1)
        elif key in (curses.KEY_DOWN, ord("j")):
            highlighted = move_menu_index(highlighted, len(VALUE_FORMAT_CHOICES), 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            return VALUE_FORMAT_CHOICES[highlighted][0]
        elif key in (27, ord("q")):
            return None


def _panel_supports_unicode() -> bool:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding


def _show_help(stdscr, *, ascii_only: bool) -> None:
    import curses

    lines = _help_lines(ascii_only=ascii_only)
    height, width = stdscr.getmaxyx()
    content_width = max((len(line) for line in lines), default=1)
    top, left, panel_height, panel_width = _centered_panel_geometry(
        height,
        width,
        content_width,
        len(lines),
    )

    try:
        panel = curses.newwin(panel_height, panel_width, top, left)
        panel.keypad(True)
        panel.erase()
        try:
            panel.box()
        except curses.error:
            pass
        visible_rows = max(0, panel_height - 2)
        section_headers = {"Signals", "Time & view", "Inspect"}
        for row, line in enumerate(lines[:visible_rows], start=1):
            attr = curses.A_BOLD if row == 1 or line in section_headers else 0
            _safe_addstr(panel, row, 2, line, attr)
        if len(lines) > visible_rows and panel_height >= 3:
            _safe_addstr(panel, panel_height - 2, 2, "resize taller for full controls", curses.A_DIM)
        panel.refresh()
        panel.getch()
    except curses.error:
        stdscr.erase()
        for row, line in enumerate(lines[: max(0, height - 1)]):
            attr = curses.A_BOLD if row == 0 else 0
            _safe_addstr(stdscr, row, 0, line, attr)
        stdscr.refresh()
        stdscr.getch()


def _draw_ruler(
    stdscr,
    vcd: VCDFile,
    state: TUIState,
    x: int,
    width: int,
    attrs: Dict[str, int],
    *,
    ascii_only: bool,
) -> None:
    if width <= 0:
        return
    labels, rule = render_timeline_ruler(
        vcd.timescale,
        state.view_start,
        state.view_end,
        width,
        ascii_only=ascii_only,
    )
    _safe_addstr(stdscr, 1, x, labels, attrs["dim"])
    _safe_addstr(stdscr, 2, x, rule, attrs["dim"])

    marker_columns: Dict[int, str] = {}
    for label, tick in (("A", state.marker_a), ("B", state.marker_b)):
        if tick is None or not state.view_start <= tick <= state.view_end:
            continue
        col = _cursor_column(tick, state.view_start, state.view_end, width)
        if col in marker_columns:
            marker_columns[col] = "M"
        else:
            marker_columns[col] = label
    for col, label in marker_columns.items():
        attr = attrs["marker_a"] if label == "A" else attrs["marker_b"]
        _safe_addstr(stdscr, 2, x + col, label, attr)

    if state.view_start <= state.cursor <= state.view_end:
        col = _cursor_column(state.cursor, state.view_start, state.view_end, width)
        _safe_addstr(stdscr, 2, x + col, "^", attrs["cursor"])


def _tree_item_text(item: TreeItem, state: TUIState, *, ascii_only: bool) -> str:
    indent = "  " * item.depth
    if item.kind == "scope":
        is_open = item.path in state.expanded_scopes
        arrow = ("v" if is_open else ">") if ascii_only else ("▼" if is_open else "▶")
        return f"{indent}{arrow} {item.label}"
    assert item.signal_index is not None
    checked = "x" if state.selected[item.signal_index] else " "
    return f"{indent}[{checked}] {item.label}"


def _clip_end(text: str, width: int, *, ascii_only: bool) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    marker = "..." if ascii_only else "…"
    if width <= len(marker):
        return text[:width]
    return text[: width - len(marker)] + marker


def _clip_middle(text: str, width: int, *, ascii_only: bool) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    marker = "..." if ascii_only else "…"
    if width <= len(marker):
        return text[:width]
    remaining = width - len(marker)
    left = (remaining + 1) // 2
    right = remaining - left
    suffix = text[-right:] if right else ""
    return text[:left] + marker + suffix


def _draw_tui(
    stdscr,
    vcd: VCDFile,
    all_signals: Sequence[Signal],
    range_start: int,
    range_end: int,
    state: TUIState,
    *,
    ascii_only: bool,
    attrs: Dict[str, int],
) -> None:
    import curses

    stdscr.erase()
    height, width = stdscr.getmaxyx()
    title = (
        f"vcdtui  cursor {vcd.timescale.format_tick(state.cursor)}  "
        f"view {vcd.timescale.format_tick(state.view_start)}..{vcd.timescale.format_tick(state.view_end)}"
    )
    _safe_addstr(stdscr, 0, 0, title, curses.A_BOLD)

    if height < 12 or width < 72:
        _safe_addstr(stdscr, 3, 0, "terminal too small; resize to at least 72x12")
        if height >= 2:
            shortcuts = shortcut_bar(width - 1, ascii_only=ascii_only)
            shortcut_x = max(0, (width - len(shortcuts)) // 2)
            _safe_addstr(stdscr, height - 2, shortcut_x, shortcuts, attrs["dim"])
        if state.status:
            _safe_addstr(stdscr, height - 1, 0, state.status)
        stdscr.refresh()
        return

    tree_items = build_tree_items(all_signals, state.expanded_scopes)
    longest_tree_line = max(
        [len("signals"), *(len(_tree_item_text(item, state, ascii_only=ascii_only)) for item in tree_items)],
        default=len("signals"),
    )
    tree_cap = min(48, max(20, width // 3))
    tree_width = max(14, min(tree_cap, longest_tree_line + 1))
    meta_width = min(28, max(18, width // 5))
    divider1_x = tree_width
    meta_x = divider1_x + 2
    divider2_x = meta_x + meta_width
    wave_x = divider2_x + 2
    wave_width = max(8, width - wave_x - 1)

    marker_height = 5 if state.marker_a is not None or state.marker_b is not None else 0
    panel_budget = max(0, height - 10)
    marker_height = min(marker_height, panel_budget)
    remaining_panel_budget = max(0, panel_budget - marker_height)
    inspector_height = 0
    if state.show_inspector and remaining_panel_budget >= 4:
        inspector_height = min(8, max(4, height // 3), remaining_panel_budget)
    main_bottom = height - 3 - marker_height - inspector_height
    header_row = 3
    content_row = 4
    main_capacity = max(1, main_bottom - content_row + 1)

    state.tree_focus, state.tree_offset = _ensure_offset(
        state.tree_focus,
        state.tree_offset,
        main_capacity,
        len(tree_items),
    )

    visible_indexes = _visible_signal_indexes(state)
    state.wave_focus, state.wave_offset = _ensure_offset(
        state.wave_focus,
        state.wave_offset,
        main_capacity,
        len(visible_indexes),
    )

    _draw_ruler(
        stdscr,
        vcd,
        state,
        wave_x,
        wave_width,
        attrs,
        ascii_only=ascii_only,
    )
    _safe_addstr(stdscr, header_row, 0, "signals", curses.A_BOLD)
    _safe_addstr(stdscr, header_row, meta_x, "shown @cursor", curses.A_BOLD)
    _safe_addstr(stdscr, header_row, wave_x, "waveform", curses.A_BOLD)

    divider = "|" if ascii_only else "│"
    for row in range(header_row, main_bottom + 1):
        _safe_addstr(stdscr, row, divider1_x, divider, attrs["dim"])
        _safe_addstr(stdscr, row, divider2_x, divider, attrs["dim"])

    tree_end = min(len(tree_items), state.tree_offset + main_capacity)
    for row, item_index in enumerate(range(state.tree_offset, tree_end), start=content_row):
        item = tree_items[item_index]
        text = _clip_end(
            _tree_item_text(item, state, ascii_only=ascii_only),
            tree_width,
            ascii_only=ascii_only,
        )
        attr = attrs["scope"] if item.kind == "scope" else 0
        if state.focus_pane == "tree" and item_index == state.tree_focus:
            attr |= attrs["focus"]
        _safe_addstr(stdscr, row, 0, text, attr)

    wave_end = min(len(visible_indexes), state.wave_offset + main_capacity)
    shown_indexes = visible_indexes[state.wave_offset:wave_end]
    cursor_in_view = state.view_start <= state.cursor <= state.view_end

    if not shown_indexes:
        _safe_addstr(stdscr, content_row, meta_x, "no signals selected", attrs["dim"])
    for row, visible_pos in enumerate(range(state.wave_offset, wave_end), start=content_row):
        signal_index = visible_indexes[visible_pos]
        signal = all_signals[signal_index]
        raw_value = signal.stream.value_at(state.cursor) or "?"
        display_format = state.display_formats[signal_index]
        value = format_signal_value(signal, raw_value, display_format)
        value_room = min(max(len(value), 1), 12)
        shown_value = _clip_middle(value, value_room, ascii_only=ascii_only)
        name_room = max(4, meta_width - value_room - 2)
        name = signal.display_reference
        if len(name) > name_room:
            name = ("…" + name[-(name_room - 1):]) if not ascii_only and name_room > 1 else name[-name_room:]
        meta = f"{name:<{name_room}} {shown_value:>{value_room}}"
        meta_attr = 0
        if state.focus_pane == "wave" and visible_pos == state.wave_focus:
            meta_attr |= attrs["focus"]
        _safe_addstr(stdscr, row, meta_x, meta, meta_attr)

        track = render_waveform_track(
            signal,
            state.view_start,
            state.view_end,
            wave_width,
            ascii_only=ascii_only,
            display_format=display_format,
        )
        track_attr = attrs["vector"] if signal.width > 1 else attrs["scalar"]
        if "x" in raw_value or "z" in raw_value:
            track_attr = attrs["bad"]
        _safe_addstr(stdscr, row, wave_x, track, track_attr)
        for tick, marker_attr in ((state.marker_a, attrs["marker_a"]), (state.marker_b, attrs["marker_b"])):
            if tick is not None and state.view_start <= tick <= state.view_end and track:
                marker_col = _cursor_column(tick, state.view_start, state.view_end, wave_width)
                glyph = cursor_track_glyph(track, marker_col)
                _safe_addstr(stdscr, row, wave_x + marker_col, glyph, marker_attr)
        if cursor_in_view and track:
            cursor_col = _cursor_column(
                state.cursor,
                state.view_start,
                state.view_end,
                wave_width,
            )
            glyph = cursor_track_glyph(track, cursor_col)
            _safe_addstr(stdscr, row, wave_x + cursor_col, glyph, attrs["cursor"])

    panel_top = main_bottom + 1
    if state.show_inspector and inspector_height > 0:
        inspector_top = panel_top
        rule = "-" if ascii_only else "─"
        _safe_addstr(stdscr, inspector_top, 0, rule * max(1, width - 1), attrs["dim"])
        _safe_addstr(stdscr, inspector_top + 1, 0, "inspection: before -> after", curses.A_BOLD)
        inspect_signals = [all_signals[index] for index in shown_indexes]
        inspection = inspect_at(inspect_signals, state.cursor)
        for offset, (item, signal_index) in enumerate(zip(inspection, shown_indexes), start=2):
            row = inspector_top + offset
            if row >= height - 1:
                break
            display_format = state.display_formats[signal_index]
            before = format_signal_value(item.signal, item.before, display_format)
            after = format_signal_value(item.signal, item.after, display_format)
            marker = "*" if item.changed else " "
            text = f"{marker} {item.signal.display_reference:<22} {before:>10} -> {after:<10}"
            attr = curses.A_BOLD if item.changed else 0
            _safe_addstr(stdscr, row, 0, text, attr)
        panel_top += inspector_height

    if marker_height > 0:
        rule = "-" if ascii_only else "─"
        _safe_addstr(stdscr, panel_top, 0, rule * max(1, width - 1), attrs["dim"])
        table_signals = [all_signals[index] for index in visible_indexes]
        table_formats = [state.display_formats[index] for index in visible_indexes]
        lines = marker_table_lines(
            vcd,
            table_signals,
            state.marker_a,
            state.marker_b,
            width - 1,
            ascii_only=ascii_only,
            display_formats=table_formats,
        )
        for offset, line in enumerate(lines[: max(0, marker_height - 1)], start=1):
            _safe_addstr(stdscr, panel_top + offset, 0, line)

    selected_count = len(visible_indexes)
    pane = state.focus_pane
    marker_status = []
    if state.marker_a is not None:
        marker_status.append(f"A={state.marker_a}")
    if state.marker_b is not None:
        marker_status.append(f"B={state.marker_b}")
    delta = marker_delta_ticks(state.marker_a, state.marker_b)
    if delta is not None:
        marker_status.append(f"delta={delta}")
    marker_text = (" | " + " ".join(marker_status)) if marker_status else ""
    status = state.status or (
        f"pane={pane} | selected {selected_count}/{len(all_signals)} | "
        f"range {range_start}..{range_end}{marker_text}"
    )
    if height >= 2:
        shortcuts = shortcut_bar(width - 1, ascii_only=ascii_only)
        shortcut_x = max(0, (width - len(shortcuts)) // 2)
        _safe_addstr(stdscr, height - 2, shortcut_x, shortcuts, attrs["dim"])
    _safe_addstr(stdscr, height - 1, 0, status)
    stdscr.refresh()


def _move_to_time(
    state: TUIState,
    tick: int,
    range_start: int,
    range_end: int,
) -> None:
    state.cursor = min(range_end, max(range_start, tick))
    state.view_start, state.view_end = recenter_window(
        state.view_start,
        state.view_end,
        state.cursor,
        range_start,
        range_end,
    )


def _tree_focused_item(signals: Sequence[Signal], state: TUIState) -> Optional[TreeItem]:
    items = build_tree_items(signals, state.expanded_scopes)
    if not items:
        return None
    state.tree_focus = min(max(0, state.tree_focus), len(items) - 1)
    return items[state.tree_focus]


def _wave_focused_signal_index(state: TUIState) -> Optional[int]:
    indexes = _visible_signal_indexes(state)
    if not indexes:
        return None
    state.wave_focus = min(max(0, state.wave_focus), len(indexes) - 1)
    return indexes[state.wave_focus]


def _navigation_signal_index(signals: Sequence[Signal], state: TUIState) -> Optional[int]:
    if state.focus_pane == "tree":
        item = _tree_focused_item(signals, state)
        if item is not None and item.kind == "signal":
            return item.signal_index
        return None
    return _wave_focused_signal_index(state)


def run_tui(
    vcd: VCDFile,
    initial_signals: Sequence[Signal],
    start: int,
    end: int,
    *,
    ascii_only: bool,
    color: bool,
) -> None:
    try:
        import curses
    except ImportError as exc:
        raise VCDTUIError("interactive mode requires the Python curses module; use --dump") from exc

    all_signals = list(vcd.signals)
    if not all_signals:
        raise VCDTUIError("trace contains no signals")

    def app(stdscr) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        attrs = _init_curses_colors(curses, color)
        state = TUIState(
            cursor=start,
            view_start=start,
            view_end=end,
            selected=_initial_selection(all_signals, initial_signals),
            display_formats=["binary"] * len(all_signals),
            expanded_scopes=all_scope_paths(all_signals),
        )
        while True:
            _draw_tui(
                stdscr,
                vcd,
                all_signals,
                start,
                end,
                state,
                ascii_only=ascii_only,
                attrs=attrs,
            )
            state.status = ""
            key = stdscr.getch()

            if key in (ord("q"), ord("Q")):
                return
            if _is_help_key(curses, key):
                _show_help(stdscr, ascii_only=ascii_only)
                continue
            if key == ord("\t"):
                state.focus_pane = "tree" if state.focus_pane == "wave" else "wave"
                continue

            if key in (curses.KEY_UP, ord("k")):
                if state.focus_pane == "tree":
                    state.tree_focus = max(0, state.tree_focus - 1)
                else:
                    state.wave_focus = max(0, state.wave_focus - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                if state.focus_pane == "tree":
                    state.tree_focus += 1
                else:
                    state.wave_focus += 1
                continue

            if key in (ord("\n"), ord("\r"), curses.KEY_ENTER) and state.focus_pane == "tree":
                # Enter shapes the tree; Space is the only thing that changes
                # what is shown, so the two can never be confused.
                item = _tree_focused_item(all_signals, state)
                if item is None:
                    continue
                if item.kind != "scope":
                    state.status = "press Space to show or hide a signal"
                    continue
                if item.path in state.expanded_scopes:
                    state.expanded_scopes.remove(item.path)
                else:
                    state.expanded_scopes.add(item.path)
                continue

            if key == ord(" "):
                if state.focus_pane == "tree":
                    item = _tree_focused_item(all_signals, state)
                    if item is None:
                        continue
                    if item.kind == "scope":
                        indexes = signal_indexes_in_scope(all_signals, item.path)
                        state.selected[:] = toggle_scope_selection(state.selected, indexes)
                        shown = state.selected[indexes[0]] if indexes else False
                        scope_name = ".".join(item.path)
                        state.status = (
                            f"{scope_name}: {len(indexes)} signals "
                            f"{'shown' if shown else 'hidden'}"
                        )
                    elif item.signal_index is not None:
                        state.selected[item.signal_index] = not state.selected[item.signal_index]
                else:
                    index = _wave_focused_signal_index(state)
                    if index is not None:
                        state.selected[index] = False
                continue

            if key in (ord("a"), _CTRL_A):
                state.selected[:] = toggle_all_selection(state.selected)
                shown = sum(state.selected)
                state.status = "all signals shown" if shown else "all signals hidden"
                continue
            if key == ord("A"):
                state.selected[:] = [False] * len(all_signals)
                state.status = "all signals hidden"
                continue
            if key in (ord("v"), ord("V")):
                signal_index = _navigation_signal_index(all_signals, state)
                if signal_index is None:
                    state.status = "focus a signal before choosing a value format"
                    continue
                signal = all_signals[signal_index]
                if signal.width <= 1:
                    state.status = f"{signal.full_name} is scalar; binary display is fixed"
                    continue
                selected_format = _prompt_value_format(
                    stdscr, signal, state.display_formats[signal_index]
                )
                if selected_format is not None:
                    state.display_formats[signal_index] = selected_format
                    state.status = f"{signal.full_name}: {selected_format}"
                continue
            if key == ord("i"):
                state.show_inspector = not state.show_inspector
                continue
            if key == ord("m"):
                state.marker_a = state.cursor
                state.status = f"marker A = {state.cursor} ({vcd.timescale.format_tick(state.cursor)})"
                continue
            if key == ord("M"):
                state.marker_b = state.cursor
                state.status = f"marker B = {state.cursor} ({vcd.timescale.format_tick(state.cursor)})"
                continue
            if key == ord("c"):
                state.marker_a = None
                state.marker_b = None
                state.status = "markers cleared"
                continue

            ctrl_forward = _ctrl_horizontal_direction(curses, key)
            if ctrl_forward is not None:
                signal_index = _navigation_signal_index(all_signals, state)
                if signal_index is None:
                    state.status = "select/focus a signal before temporal navigation"
                    continue
                signal = all_signals[signal_index]
                tick = next_edge(signal.stream, state.cursor, "any", forward=ctrl_forward)
                if tick is None:
                    state.status = (
                        f"no {'next' if ctrl_forward else 'previous'} binary edge "
                        f"for {signal.full_name}"
                    )
                else:
                    _move_to_time(state, tick, start, end)
                    state.status = (
                        f"binary edge: {signal.full_name} @ {tick} "
                        f"({vcd.timescale.format_tick(tick)})"
                    )
                continue

            boundary = _range_boundary_for_key(curses, key, start, end)
            if boundary is not None:
                _move_to_time(state, boundary, start, end)
            elif key in (curses.KEY_LEFT, ord("h")):
                _move_to_time(state, state.cursor - 1, start, end)
            elif key in (curses.KEY_RIGHT, ord("l")):
                _move_to_time(state, state.cursor + 1, start, end)
            elif key in (ord("g"), ord("G")):
                tick, state.status = _prompt_goto(
                    stdscr, vcd, start, end, stdscr.getmaxyx()[0] - 1
                )
                if tick is not None:
                    _move_to_time(state, tick, start, end)
            elif key in (ord("+"), ord("=")):
                state.view_start, state.view_end = zoom_window(
                    state.view_start,
                    state.view_end,
                    state.cursor,
                    start,
                    end,
                    zoom_in=True,
                )
            elif key == ord("-"):
                state.view_start, state.view_end = zoom_window(
                    state.view_start,
                    state.view_end,
                    state.cursor,
                    start,
                    end,
                    zoom_in=False,
                )
            elif key == ord("<"):
                state.view_start, state.view_end = pan_window(
                    state.view_start,
                    state.view_end,
                    start,
                    end,
                    forward=False,
                )
            elif key == ord(">"):
                state.view_start, state.view_end = pan_window(
                    state.view_start,
                    state.view_end,
                    start,
                    end,
                    forward=True,
                )
            elif key in (
                ord("n"), ord("N"), ord("e"), ord("E"),
                ord("r"), ord("R"), ord("f"), ord("F"),
            ):
                signal_index = _navigation_signal_index(all_signals, state)
                if signal_index is None:
                    state.status = "select/focus a signal before temporal navigation"
                    continue
                signal = all_signals[signal_index]
                forward = chr(key).islower()
                if key in (ord("n"), ord("N")):
                    tick = next_transition(signal.stream, state.cursor, forward=forward)
                    label = "transition"
                elif key in (ord("e"), ord("E")):
                    tick = next_edge(signal.stream, state.cursor, "any", forward=forward)
                    label = "binary edge"
                elif key in (ord("r"), ord("R")):
                    tick = next_edge(signal.stream, state.cursor, "rising", forward=forward)
                    label = "rising edge"
                else:
                    tick = next_edge(signal.stream, state.cursor, "falling", forward=forward)
                    label = "falling edge"
                if tick is None:
                    state.status = f"no {'next' if forward else 'previous'} {label} for {signal.full_name}"
                else:
                    _move_to_time(state, tick, start, end)
                    state.status = (
                        f"{label}: {signal.full_name} @ {tick} "
                        f"({vcd.timescale.format_tick(tick)})"
                    )
            elif key == curses.KEY_RESIZE:
                continue

    try:
        curses.wrapper(app)
    except curses.error as exc:
        raise VCDTUIError(f"terminal UI initialization failed: {exc}; use --dump") from exc


def run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    path = _require_file(args, parser)
    vcd = parse_vcd(path)
    for warning in vcd.warnings:
        print(f"vcdtui: warning: {warning}", file=sys.stderr)
    if args.scope is not None:
        vcd = scoped_view(vcd, args.scope)

    if args.list:
        _print_signals(vcd.signals)
        return 0
    if args.find is not None:
        _print_signals(vcd.find(args.find))
        return 0

    selection_warnings: List[str] = []
    signals = select_signals(vcd, args.signals, warnings=selection_warnings)
    for warning in selection_warnings:
        print(f"vcdtui: warning: {warning}", file=sys.stderr)
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
    run_tui(
        vcd,
        signals,
        start,
        end,
        ascii_only=args.ascii,
        color=not args.no_color,
    )
    return 0


def _discard_stdout() -> None:
    """Point stdout at /dev/null so interpreter shutdown will not flush a dead pipe."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args, parser)
    except KeyboardInterrupt:
        # Quitting with Ctrl-C is normal use, not a crash.
        return 130
    except BrokenPipeError:
        # The reader went away, as in "vcdtui trace.vcd --list | head".
        _discard_stdout()
        return 141
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
