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


@dataclass
class TUIState:
    cursor: int
    view_start: int
    view_end: int
    selected: List[bool]
    focus_index: int = 0
    browser_offset: int = 0
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


def _cursor_column(cursor: int, start: int, end: int, width: int) -> int:
    if width <= 1 or start == end:
        return 0
    return min(width - 1, max(0, ((cursor - start) * (width - 1)) // (end - start)))


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
        raw = stdscr.getstr(status_row, min(len(prompt), max(0, width - 2)), max(1, width - len(prompt) - 2))
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
    attrs = {"scalar": 0, "vector": 0, "bad": 0, "cursor": 0, "dim": 0, "focus": 0}
    if not enabled or not curses.has_colors():
        attrs["focus"] = curses.A_REVERSE
        attrs["dim"] = curses.A_DIM
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
            cursor=curses.color_pair(4) | curses.A_BOLD,
            dim=curses.A_DIM,
            focus=curses.A_REVERSE,
        )
    except curses.error:
        return {
            "scalar": 0,
            "vector": 0,
            "bad": 0,
            "cursor": curses.A_BOLD,
            "dim": curses.A_DIM,
            "focus": curses.A_REVERSE,
        }
    return attrs


def _ensure_browser_focus(state: TUIState, capacity: int, count: int) -> None:
    if count <= 0:
        state.focus_index = 0
        state.browser_offset = 0
        return
    state.focus_index = min(max(0, state.focus_index), count - 1)
    if capacity <= 0:
        state.browser_offset = state.focus_index
        return
    if state.focus_index < state.browser_offset:
        state.browser_offset = state.focus_index
    elif state.focus_index >= state.browser_offset + capacity:
        state.browser_offset = state.focus_index - capacity + 1
    max_offset = max(0, count - capacity)
    state.browser_offset = min(max(0, state.browser_offset), max_offset)


def _show_help(stdscr) -> None:
    import curses

    lines = [
        "vcdtui course-core keys",
        "",
        "Up/Down        focus signal in browser",
        "Space          show/hide focused signal",
        "a / A          show all / hide all signals",
        "Left/Right     move cursor by one VCD tick",
        "< / >          pan waveform viewport",
        "+ / -          zoom in / out around cursor",
        "n / N          next / previous transition (focused signal)",
        "r / R          next / previous rising edge (focused signal)",
        "f / F          next / previous falling edge (focused signal)",
        "0 / $          cursor to active range start / end",
        "g              goto exact tick or physical time",
        "?              this help",
        "q              quit",
        "",
        "Any key returns.",
    ]
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    for row, line in enumerate(lines[: max(0, height - 1)]):
        attr = curses.A_BOLD if row == 0 else 0
        _safe_addstr(stdscr, row, 0, line, attr)
    if width < 48 and height > 0:
        _safe_addstr(stdscr, height - 1, 0, "resize wider for full help")
    stdscr.refresh()
    stdscr.getch()


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
        f"view={state.view_start}..{state.view_end} range={range_start}..{range_end}"
    )
    _safe_addstr(stdscr, 0, 0, title, curses.A_BOLD)
    _safe_addstr(
        stdscr,
        1,
        0,
        "Up/Down signal  Space toggle  Left/Right cursor  +/- zoom  </> pan  n/r/f edges  ? help",
        attrs["dim"],
    )

    if height < 12 or width < 60:
        _safe_addstr(stdscr, 3, 0, "terminal too small; resize to at least 60x12")
        if state.status:
            _safe_addstr(stdscr, height - 1, 0, state.status)
        stdscr.refresh()
        return

    browser_width = min(42, max(22, width // 3))
    split_x = browser_width
    wave_x = split_x + 2
    wave_width = max(8, width - wave_x - 1)
    browser_capacity = max(1, height - 5)
    _ensure_browser_focus(state, browser_capacity, len(all_signals))

    _safe_addstr(stdscr, 3, 0, "signals", curses.A_BOLD)
    _safe_addstr(stdscr, 3, wave_x, "waveform", curses.A_BOLD)
    divider = "|" if ascii_only else "│"
    for row in range(3, height - 1):
        _safe_addstr(stdscr, row, split_x, divider, attrs["dim"])

    end_index = min(len(all_signals), state.browser_offset + browser_capacity)
    for row, index in enumerate(range(state.browser_offset, end_index), start=4):
        signal = all_signals[index]
        checked = "x" if state.selected[index] else " "
        prefix = f"[{checked}] "
        room = max(1, browser_width - len(prefix) - 1)
        name = signal.full_name
        if len(name) > room:
            name = "…" + name[-(room - 1) :] if not ascii_only and room > 1 else name[-room:]
        attr = attrs["focus"] if index == state.focus_index else 0
        _safe_addstr(stdscr, row, 0, prefix + name, attr)

    visible = selected_signals(all_signals, state.selected)
    right_height = height - 5
    wave_rows = max(1, right_height // 2)
    shown = visible[:wave_rows]
    cursor_in_view = state.view_start <= state.cursor <= state.view_end
    cursor_char = "|" if ascii_only else "│"

    row = 4
    if not shown:
        _safe_addstr(stdscr, row, wave_x, "no signals selected; use Space in the browser", attrs["dim"])
    for signal in shown:
        label_width = min(18, max(8, wave_width // 4))
        track_width = max(4, wave_width - label_width - 2)
        label = signal.reference
        if len(label) > label_width:
            label = label[-label_width:]
        wave = list(
            sample_waveform(
                signal,
                state.view_start,
                state.view_end,
                track_width,
                ascii_only=ascii_only,
            )
        )
        track_cursor_col: Optional[int] = None
        if cursor_in_view:
            track_cursor_col = _cursor_column(
                state.cursor, state.view_start, state.view_end, track_width
            )
            if wave:
                wave[track_cursor_col] = cursor_char
        value = signal.stream.value_at(state.cursor) or "?"
        attr = attrs["vector"] if signal.width > 1 else attrs["scalar"]
        if "x" in value or "z" in value:
            attr = attrs["bad"]
        _safe_addstr(stdscr, row, wave_x, label.rjust(label_width), attrs["dim"])
        track_x = wave_x + label_width + 1
        _safe_addstr(stdscr, row, track_x, "".join(wave), attr)
        if track_cursor_col is not None:
            _safe_addstr(stdscr, row, track_x + track_cursor_col, cursor_char, attrs["cursor"])
        row += 1

    inspector_row = max(row + 1, 4 + wave_rows + 1)
    if inspector_row < height - 2:
        _safe_addstr(stdscr, inspector_row, wave_x, "at cursor: before -> after", curses.A_BOLD)
        inspector_row += 1
        for item in inspect_at(shown, state.cursor):
            if inspector_row >= height - 1:
                break
            before = item.before or "?"
            after = item.after or "?"
            marker = "*" if item.changed else " "
            text = f"{marker} {item.signal.reference:<16} {before:>8} -> {after:<8}"
            attr = curses.A_BOLD if item.changed else 0
            _safe_addstr(stdscr, inspector_row, wave_x, text, attr)
            inspector_row += 1

    selected_count = sum(1 for enabled in state.selected if enabled)
    focus_name = all_signals[state.focus_index].full_name if all_signals else "-"
    status = state.status or (
        f"selected {selected_count}/{len(all_signals)} | focused {focus_name} | q quit"
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
            if key in (curses.KEY_UP, ord("k")):
                state.focus_index = max(0, state.focus_index - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                state.focus_index = min(len(all_signals) - 1, state.focus_index + 1)
            elif key == ord(" "):
                state.selected[state.focus_index] = not state.selected[state.focus_index]
            elif key == ord("a"):
                state.selected[:] = [True] * len(all_signals)
            elif key == ord("A"):
                state.selected[:] = [False] * len(all_signals)
            elif key in (curses.KEY_LEFT, ord("h")):
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
                signal = all_signals[state.focus_index]
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
                    state.status = f"{label}: {signal.full_name} @ {tick} ({vcd.timescale.format_tick(tick)})"
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
