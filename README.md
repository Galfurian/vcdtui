# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and has two first-class interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal view for temporal exploration.

## Status

The course core is complete through Milestone 4. M4.1 refines the interactive presentation without changing the parser, exact-time, dump, or temporal-navigation contracts.

The implementation includes the VCD parser, exact time model, signal queries, deterministic `--dump`, hierarchical interactive signal selection, pan/zoom, an exact cursor, goto, before/after inspection, and transition/edge navigation.

The layers share one model: the interactive UI consumes the same parser, selected signals, sparse transition streams, and exact-time rules used by non-interactive mode.

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

The main view is deliberately aligned as:

```text
signal tree | shown @cursor | waveform
```

The tree contains hierarchical scopes and all signals. The middle column lists displayed signals with their exact value at the cursor. The right pane shows their temporal history.

Controls:

```text
Tab             switch focus: signal tree / waveform
Up / Down       move within the focused pane
j / k           same as Down / Up
Enter           expand/collapse focused scope in the tree
Space           show/hide the focused signal
a / A           show all / hide all signals

Left / Right    move cursor one VCD tick
h / l           same as Left / Right
< / >           pan the waveform viewport
+ / -           zoom in / out around the cursor

n / N           next / previous transition
r / R           next / previous rising edge
f / F           next / previous falling edge

0               cursor to active range start
$               cursor to active range end
g               goto exact tick or physical time
i               show/hide before/after inspector
?               full key help
q               quit
```

Lowercase temporal-navigation keys move forward in time; uppercase variants move backward. Rising and falling edges are recognized only for clean scalar `0 -> 1` and `1 -> 0` transitions. `x` and `z` transitions are not guessed into edges.

The active range is the exact `--from` / `--to` range. Pan and zoom change only the viewport inside that range. Cursor and edge navigation remain exact in raw VCD ticks; when navigation moves outside the current viewport, the viewport recenters without quantizing the cursor.

### Waveform representation

Scalar waveforms make transitions visible directly:

```text
rising    ____/‾‾‾‾
falling   ‾‾‾‾\____
```

ASCII mode uses `-` for the high level. `x` and `z` remain explicit. Vector tracks place their values directly on the trace when an interval has enough columns.

The cursor is non-destructive: the waveform glyph under the cursor is preserved and redrawn with a cursor attribute rather than replaced by a vertical-bar character. A cursor landing on `/`, `\`, or a bus label therefore does not erase the evidence underneath it.

### Before/after inspection

The inspector is hidden by default and toggled with `i`. Its semantics remain:

```text
before = last value whose VCD timestamp is strictly less than cursor
after  = value after all changes at cursor have been applied
```

A `*` marks signals whose values differ across the cursor timestamp.

## Course-core boundary

Milestones 1 through 4 define the complete teaching-oriented core. M4.1 only improves how that core is presented.

Dual markers and delta-time measurement are the next small post-core capability. Command mode, configuration files, mouse interaction, and large-file indexing remain optional post-core work and are not required for qualification.

See `docs/M4_COURSE_CORE.md` for navigation semantics and `docs/M4_1_UI_POLISH.md` for the presentation contract.

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
