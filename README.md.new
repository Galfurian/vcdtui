# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and has two first-class interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal view for temporal exploration.

## Status

The core parser, exact-time model, deterministic dump, hierarchical signal browser, waveform navigation, markers, and time ruler are implemented. Current work is focused on qualification fixtures and compatibility checks rather than expanding the feature set.

The interactive UI and non-interactive commands share the same parsed VCD model, sparse transition streams, signal selection rules, and exact-time semantics.

## Current commands

```bash
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,start,dec,count,stop --dump
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --from 20ns --to 50ns --dump --ascii --no-color
python3 vcdtui.py examples/counter.vcd --signals clk,start,dec,count,stop
python3 vcdtui.py --version
```

`--signals` accepts comma-separated selectors. Exact full names or signal references are preferred; otherwise a selector matches case-insensitive substrings of hierarchical names. A selector that matches nothing is an error.

`--from` and `--to` accept raw VCD ticks or exact physical times such as `20ns`. Physical times that do not align exactly with the VCD timescale are rejected rather than rounded.

## Deterministic dump

`--dump` prints a terminal-width-independent event matrix. Rows are emitted for the selected range boundaries and for timestamps where a selected value stream changes. Values on a row are the values after changes at that timestamp have been applied.

For qualification and snapshots, use:

```bash
python3 vcdtui.py trace.vcd --signals clk,count --dump --ascii --no-color
```

When stdout is redirected, ANSI color is disabled automatically. `--no-color` makes that choice explicit. Unicode separators are the default; `--ascii` uses only ASCII separators.

The raw `tick` column is the source-of-truth timestamp. The `time` column is an exact human-readable representation derived without floating-point arithmetic.

## Interactive view

Running without `--dump` requires stdin and stdout to be attached to a usable terminal. The program checks this before importing or initializing `curses`; non-interactive commands therefore remain independent of terminal setup.

The main view is aligned as:

```text
signal tree | shown @cursor | waveform
```

The top of the terminal stays intentionally minimal: current cursor/view information followed by the time ruler. A compact, width-aware shortcut bar lives at the bottom. Press `F1` or `?` for the complete centered control panel.

The tree contains hierarchical scopes and all signals. The middle column lists displayed signals with their exact value at the cursor. The right pane shows their temporal history.

### Controls

```text
Tab                 switch focus: signal tree / waveform
Up / Down, j / k    move within the focused pane
Enter               expand/collapse focused scope
Space               show/hide focused signal
a / A               show all / hide all signals
v                   choose focused vector display format

Left / Right, h / l move cursor one VCD tick
Ctrl+Left / Right   previous / next clean binary edge when supported
Home / End          cursor to active range start / end
0 / $               aliases for Home / End
g                   goto exact tick or physical time
< / >               pan waveform viewport
+ / -               zoom in / out around cursor

n / N               next / previous transition
e / E               next / previous clean binary edge
r / R               next / previous rising edge
f / F               next / previous falling edge

i                   show/hide before/after inspector
m / M               place or move marker A / B
c                   clear both markers
F1 / ?              full centered help
q                   quit
```

Lowercase temporal-navigation keys move forward in time; uppercase variants move backward. Clean binary edges are only `0 -> 1` and `1 -> 0`. Transitions involving `x` or `z` are never guessed into edges.

Modified Ctrl+arrow sequences vary by terminal, so `e/E` is the portable contract for previous/next clean binary edge.

### Time ruler

The waveform pane includes a deterministic time ruler. Major spacing follows a `1 / 2 / 5 x 10^n` sequence in raw VCD ticks, while displayed physical labels use the exact `TimeScale` formatter.

Pan and zoom change only the viewport inside the active `--from` / `--to` range. Cursor and edge navigation remain exact in raw VCD ticks; when navigation leaves the viewport, the viewport recenters without quantizing the cursor.

### Waveform representation

Scalar waveforms make transitions visible directly:

```text
rising    ____/‾‾‾‾
falling   ‾‾‾‾\____
```

ASCII mode uses `-` for the high level. `x` and `z` remain explicit. Vector tracks place their values directly on the trace when an interval has enough columns.

The cursor and markers are non-destructive: they change cell attributes rather than replacing the waveform glyph underneath them. Landing on `/`, `\`, or a bus label therefore does not erase trace evidence.

### Per-signal vector formats

Press `v` while a vector signal is focused to choose binary, hexadecimal, unsigned decimal, or signed decimal presentation for that signal. The underlying VCD value remains binary; the format affects only presentation. Scalar `0/1/x/z` values remain unchanged, and vectors containing `x` or `z` stay as bit patterns rather than being coerced to a number.

See `docs/VALUE_FORMATS.md` for the exact semantics.

### Before/after inspection

The inspector is hidden by default and toggled with `i`:

```text
before = last value whose VCD timestamp is strictly less than cursor
after  = value after all changes at cursor have been applied
```

A `*` marks signals whose values differ across the cursor timestamp.

### Markers

`m` places or moves marker A; `M` places or moves marker B. The marker table shows post-change values for currently displayed signals. With both markers present:

```text
delta = B - A
```

The delta is signed and remains exact in raw ticks and physical-time formatting.

## Qualification corpus

Hand-readable supported and deliberately malformed traces live under `examples/qualification/`. They cover nested scopes, aliases, unusual identifier codes, `x/z`, sparse initialization, exact times, and a richer interactive showcase. Generated simulator traces can be added under `examples/qualification/generated/` once simulator versions are pinned.

## Requirements

```text
Python >= 3.10
runtime dependencies: none outside the Python standard library
qualified userspace target: Linux
```

Interactive mode additionally requires the standard-library `curses` module available in the target Python installation.

## Development checks

```bash
python3 -m unittest discover -s tests -v
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --dump --ascii --no-color
```

See `DESIGN.md` for the parser contract, supported VCD subset, data model, exact-time rules, TTY behavior, and qualification boundary. Focused interaction notes live under `docs/`.
