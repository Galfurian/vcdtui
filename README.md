# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and has two first-class interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal view for temporal exploration.

## Status

Milestone 1 provides the VCD parser and signal queries. Milestone 2 provides deterministic non-interactive timeline dumping. Milestone 3 adds the first interactive `curses` view with a cursor, exact goto, compact waveform sampling, colors, and before/after inspection.

The project intentionally builds these layers in order: the interactive UI consumes the same parser, selected signals, exact-time model, and sparse transition streams used by non-interactive mode.

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

Running without `--dump` requires stdin and stdout to be attached to a usable terminal. The program checks this before importing/initializing `curses`; non-interactive commands therefore remain independent of terminal setup.

Current M3 controls:

```text
Left / Right     move cursor one VCD tick
h / l            same as Left / Right
0                cursor to active range start
$                cursor to active range end
g                goto exact tick or physical time
?                show key help
q                quit
```

The active range is the same exact `--from` / `--to` range used by `--dump`.

At the cursor the TUI shows, for every visible selected signal:

```text
before -> after
```

with the following precise semantics:

```text
before = last value whose VCD timestamp is strictly less than cursor
 after = value after all changes at cursor have been applied
```

A `*` marks signals for which those values differ. This makes an edge such as `count: 0001 -> 0000` and `stop: 0 -> 1` directly visible at the same timestamp.

The minimal waveform uses `_`/`‾` for scalar low/high states in Unicode mode (`_`/`-` in ASCII mode), `x`/`z` for unknown/high-impedance states, and `=` as a compact vector-state track. A separate vertical cursor overlays the waveform.

Signal browsing, pan/zoom, and edge-to-edge navigation are intentionally M4 work.

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

See `DESIGN.md` for the project contract, supported VCD subset, data model, exact time rules, TTY behavior, temporal semantics, and milestones.
