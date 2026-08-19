# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and has two first-class interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal view for temporal exploration.

## Status

The course core is complete through Milestone 4.

The implementation now includes the VCD parser, exact time model, signal queries, deterministic `--dump`, interactive signal selection, pan/zoom, an exact cursor, goto, before/after inspection, and transition/edge navigation.

The layers intentionally share one model: the interactive UI consumes the same parser, selected signals, sparse transition streams, and exact-time rules used by non-interactive mode.

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

Course-core controls:

```text
Up / Down       focus a signal in the browser
j / k           same as Down / Up
Space           show or hide the focused signal
a / A           show all / hide all signals

Left / Right    move cursor one VCD tick
h / l           same as Left / Right
< / >           pan the waveform viewport
+ / -           zoom in / out around the cursor

n / N           next / previous transition of focused signal
r / R           next / previous rising edge of focused signal
f / F           next / previous falling edge of focused signal

0               cursor to active range start
$               cursor to active range end
g               goto exact tick or physical time
?               full key help
q               quit
```

Lowercase navigation keys move forward in time; uppercase variants move backward. Rising and falling edges are recognized only for clean scalar `0 -> 1` and `1 -> 0` transitions. `x` and `z` transitions are not guessed into edges.

The active range is the exact `--from` / `--to` range. Pan and zoom change only the viewport inside that range. Cursor and edge navigation remain exact in raw VCD ticks; when navigation moves outside the current viewport, the viewport recenters without changing its span.

At the cursor the TUI shows, for visible selected signals:

```text
before -> after
```

with the precise semantics:

```text
before = last value whose VCD timestamp is strictly less than cursor
after  = value after all changes at cursor have been applied
```

A `*` marks signals for which those values differ. This makes simultaneous evidence such as `count: 0001 -> 0000` and `stop: 0 -> 1` directly visible at one timestamp.

The waveform uses `_`/`‾` for scalar low/high states in Unicode mode (`_`/`-` in ASCII mode), `x`/`z` for unknown/high-impedance states, and `=` as a compact vector-state track. A separate vertical cursor overlays the waveform.

## Course-core boundary

Milestones 1 through 4 define the complete teaching-oriented core. Features such as dual markers, command mode, configuration files, mouse interaction, and large-file indexing are intentionally post-core and are not required for qualification.

See `docs/M4_COURSE_CORE.md` for the navigation semantics and completion boundary.

## Requirements

```text
Python >= 3.10
runtime dependencies: none outside the Python standard library
qualified userspace target: Linux
```

Interactive mode additionally requires the standard-library `curses` module available in the qualified Linux Python installation.

## Development checks

```bash
python3 -m unittest discover -s tests -v
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --dump --ascii --no-color
```

See `DESIGN.md` for the project contract, supported VCD subset, data model, exact time rules, TTY behavior, temporal semantics, and milestone boundary.
