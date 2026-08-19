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
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

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

    def value_before(self, time: int) -> Optional[str]:
        index = bisect_left(self.changes, time, key=lambda change: change.time) - 1
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
    status: str = ""


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


def inspect_at(signals: Sequence[Signal], cursor: int) -> List[Inspection]:
    return [
        Inspection(
            signal=signal,
            before=signal.stream.value_before(cursor),
            after=signal.stream.value_at(cursor),
        )
        for signal in signals
    ]


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
    if stream.width != 1:
        return []
    if kind not in ("rising", "falling"):
        raise ValueError(f"unknown edge kind {kind!r}")
    result: List[int] = []
    previous: Optional[str] = None
    for change in stream.changes:
        current = change.value
        if kind == "rising" and previous == "0" and current == "1":
            result.append(change.time)
        elif kind == "falling" and previous == "1" and current == "0":
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
            items.append(TreeItem("signal", signal.reference, depth, parent, index))

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
) -> str:
    if width <= 0:
        return ""
    ticks = _sample_ticks(start, end, width)
    values = [signal.stream.value_at(tick) or "?" for tick in ticks]
    horizontal = "-" if ascii_only else "─"
    boundary = "|" if ascii_only else "│"
    line = [horizontal] * width

    run_start = 0
    while run_start < width:
        value = values[run_start]
        run_end = run_start + 1
        while run_end < width and values[run_end] == value:
            run_end += 1
        if run_start > 0:
            line[run_start] = boundary
        content_start = run_start + (1 if run_start > 0 else 0)
        available = max(0, run_end - content_start)
        if available > 0:
            label = value[:available]
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
) -> str:
    if signal.width == 1:
        return render_scalar_track(signal, start, end, width, ascii_only=ascii_only)
    return render_bus_track(signal, start, end, width, ascii_only=ascii_only)


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
        attrs.update(
            scalar=curses.color_pair(1),
            vector=curses.color_pair(2),
            bad=curses.color_pair(3),
            cursor=curses.color_pair(4) | curses.A_REVERSE | curses.A_BOLD,
            scope=curses.color_pair(2) | curses.A_BOLD,
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


def _show_help(stdscr) -> None:
    import curses

    lines = [
        "vcdtui keys",
        "",
        "Tab            switch focus: signal tree / waveform",
        "Up/Down j/k    move within focused pane",
        "Enter          expand/collapse scope in tree",
        "Space          show/hide focused signal",
        "a / A          show all / hide all signals",
        "Left/Right h/l move cursor by one VCD tick",
        "< / >          pan waveform viewport",
        "+ / -          zoom in / out around cursor",
        "n / N          next / previous transition",
        "r / R          next / previous rising edge",
        "f / F          next / previous falling edge",
        "0 / $          cursor to active range start / end",
        "g              goto exact tick or physical time",
        "i              show/hide before/after inspector",
        "?              this help",
        "q              quit",
        "",
        "Lowercase temporal keys move forward; uppercase move backward.",
        "Any key returns.",
    ]
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    for row, line in enumerate(lines[: max(0, height - 1)]):
        attr = curses.A_BOLD if row == 0 else 0
        _safe_addstr(stdscr, row, 0, line, attr)
    if width < 56 and height > 0:
        _safe_addstr(stdscr, height - 1, 0, "resize wider for full help")
    stdscr.refresh()
    stdscr.getch()


def _draw_ruler(stdscr, vcd: VCDFile, state: TUIState, x: int, width: int, attrs: Dict[str, int]) -> None:
    if width <= 4:
        return
    left = vcd.timescale.format_tick(state.view_start)
    right = vcd.timescale.format_tick(state.view_end)
    _safe_addstr(stdscr, 2, x, left, attrs["dim"])
    _safe_addstr(stdscr, 2, x + max(0, width - len(right)), right, attrs["dim"])
    if state.view_start <= state.cursor <= state.view_end:
        col = _cursor_column(state.cursor, state.view_start, state.view_end, width)
        _safe_addstr(stdscr, 2, x + col, "^", attrs["cursor"])


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
        f"vcdtui cursor={state.cursor} ({vcd.timescale.format_tick(state.cursor)}) "
        f"view={state.view_start}..{state.view_end}"
    )
    _safe_addstr(stdscr, 0, 0, title, curses.A_BOLD)
    _safe_addstr(
        stdscr,
        1,
        0,
        "Tab pane  Space toggle  arrows cursor/tree  +/- zoom  </> pan  n/r/f edges  i inspect  ? help",
        attrs["dim"],
    )

    if height < 12 or width < 72:
        _safe_addstr(stdscr, 3, 0, "terminal too small; resize to at least 72x12")
        if state.status:
            _safe_addstr(stdscr, height - 1, 0, state.status)
        stdscr.refresh()
        return

    tree_width = min(34, max(22, width // 4))
    meta_width = min(28, max(18, width // 5))
    divider1_x = tree_width
    meta_x = divider1_x + 2
    divider2_x = meta_x + meta_width
    wave_x = divider2_x + 2
    wave_width = max(8, width - wave_x - 1)

    inspector_height = 0
    if state.show_inspector:
        inspector_height = min(8, max(5, height // 3))
    main_bottom = height - 2 - inspector_height
    main_capacity = max(1, main_bottom - 4)

    tree_items = build_tree_items(all_signals, state.expanded_scopes)
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

    _safe_addstr(stdscr, 3, 0, "signals", curses.A_BOLD)
    _safe_addstr(stdscr, 3, meta_x, "shown @cursor", curses.A_BOLD)
    _safe_addstr(stdscr, 3, wave_x, "waveform", curses.A_BOLD)
    _draw_ruler(stdscr, vcd, state, wave_x, wave_width, attrs)

    divider = "|" if ascii_only else "│"
    for row in range(3, main_bottom + 1):
        _safe_addstr(stdscr, row, divider1_x, divider, attrs["dim"])
        _safe_addstr(stdscr, row, divider2_x, divider, attrs["dim"])

    tree_end = min(len(tree_items), state.tree_offset + main_capacity)
    for row, item_index in enumerate(range(state.tree_offset, tree_end), start=4):
        item = tree_items[item_index]
        indent = "  " * item.depth
        if item.kind == "scope":
            is_open = item.path in state.expanded_scopes
            arrow = ("v" if is_open else ">") if ascii_only else ("▼" if is_open else "▶")
            text = f"{indent}{arrow} {item.label}"
            attr = attrs["scope"]
        else:
            assert item.signal_index is not None
            checked = "x" if state.selected[item.signal_index] else " "
            text = f"{indent}[{checked}] {item.label}"
            attr = 0
        if state.focus_pane == "tree" and item_index == state.tree_focus:
            attr |= attrs["focus"]
        _safe_addstr(stdscr, row, 0, text, attr)

    wave_end = min(len(visible_indexes), state.wave_offset + main_capacity)
    shown_indexes = visible_indexes[state.wave_offset:wave_end]
    cursor_in_view = state.view_start <= state.cursor <= state.view_end

    if not shown_indexes:
        _safe_addstr(stdscr, 4, meta_x, "no signals selected", attrs["dim"])
    for row, visible_pos in enumerate(range(state.wave_offset, wave_end), start=4):
        signal_index = visible_indexes[visible_pos]
        signal = all_signals[signal_index]
        value = signal.stream.value_at(state.cursor) or "?"
        value_room = min(max(signal.width, 1), 10)
        name_room = max(4, meta_width - value_room - 2)
        name = signal.reference
        if len(name) > name_room:
            name = ("…" + name[-(name_room - 1):]) if not ascii_only and name_room > 1 else name[-name_room:]
        meta = f"{name:<{name_room}} {value:>{value_room}}"
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
        )
        track_attr = attrs["vector"] if signal.width > 1 else attrs["scalar"]
        if "x" in value or "z" in value:
            track_attr = attrs["bad"]
        _safe_addstr(stdscr, row, wave_x, track, track_attr)
        if cursor_in_view and track:
            cursor_col = _cursor_column(
                state.cursor,
                state.view_start,
                state.view_end,
                wave_width,
            )
            glyph = cursor_track_glyph(track, cursor_col)
            _safe_addstr(stdscr, row, wave_x + cursor_col, glyph, attrs["cursor"])

    if state.show_inspector:
        inspector_top = main_bottom + 1
        rule = "-" if ascii_only else "─"
        _safe_addstr(stdscr, inspector_top, 0, rule * max(1, width - 1), attrs["dim"])
        _safe_addstr(stdscr, inspector_top + 1, 0, "inspection: before -> after", curses.A_BOLD)
        inspect_signals = [all_signals[index] for index in shown_indexes]
        for offset, item in enumerate(inspect_at(inspect_signals, state.cursor), start=2):
            row = inspector_top + offset
            if row >= height - 1:
                break
            before = item.before or "?"
            after = item.after or "?"
            marker = "*" if item.changed else " "
            text = f"{marker} {item.signal.reference:<22} {before:>10} -> {after:<10}"
            attr = curses.A_BOLD if item.changed else 0
            _safe_addstr(stdscr, row, 0, text, attr)

    selected_count = len(visible_indexes)
    pane = state.focus_pane
    status = state.status or (
        f"pane={pane} | selected {selected_count}/{len(all_signals)} | "
        f"range {range_start}..{range_end} | q quit"
    )
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
                item = _tree_focused_item(all_signals, state)
                if item is not None:
                    if item.kind == "scope":
                        if item.path in state.expanded_scopes:
                            state.expanded_scopes.remove(item.path)
                        else:
                            state.expanded_scopes.add(item.path)
                    elif item.signal_index is not None:
                        state.selected[item.signal_index] = not state.selected[item.signal_index]
                continue

            if key == ord(" "):
                if state.focus_pane == "tree":
                    item = _tree_focused_item(all_signals, state)
                    if item is not None and item.kind == "signal" and item.signal_index is not None:
                        state.selected[item.signal_index] = not state.selected[item.signal_index]
                else:
                    index = _wave_focused_signal_index(state)
                    if index is not None:
                        state.selected[index] = False
                continue

            if key == ord("a"):
                state.selected[:] = [True] * len(all_signals)
                continue
            if key == ord("A"):
                state.selected[:] = [False] * len(all_signals)
                continue
            if key == ord("i"):
                state.show_inspector = not state.show_inspector
                continue

            if key in (curses.KEY_LEFT, ord("h")):
                _move_to_time(state, state.cursor - 1, start, end)
            elif key in (curses.KEY_RIGHT, ord("l")):
                _move_to_time(state, state.cursor + 1, start, end)
            elif key == ord("0"):
                _move_to_time(state, start, start, end)
            elif key == ord("$"):
                _move_to_time(state, end, start, end)
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
            elif key in (ord("n"), ord("N"), ord("r"), ord("R"), ord("f"), ord("F")):
                signal_index = _navigation_signal_index(all_signals, state)
                if signal_index is None:
                    state.status = "select/focus a signal before temporal navigation"
                    continue
                signal = all_signals[signal_index]
                forward = chr(key).islower()
                if key in (ord("n"), ord("N")):
                    tick = next_transition(signal.stream, state.cursor, forward=forward)
                    label = "transition"
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
            elif key == ord("?"):
                _show_help(stdscr)

    try:
        curses.wrapper(app)
    except curses.error as exc:
        raise VCDTUIError(f"terminal UI initialization failed: {exc}; use --dump") from exc


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
    run_tui(
        vcd,
        signals,
        start,
        end,
        ascii_only=args.ascii,
        color=not args.no_color,
    )
    return 0


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
