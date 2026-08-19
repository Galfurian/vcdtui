# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and is designed around two equally important interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal waveform view for temporal exploration.

## Status

The project is under active construction.

Milestone 1 provides the VCD parser and signal queries. Milestone 2 adds deterministic non-interactive timeline dumping. The interactive UI remains intentionally staged later so it can be built on the same tested parser, signal-selection, and exact-time model.

## Current commands

```bash
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,start,dec,count,stop --dump
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --from 20ns --to 50ns --dump --ascii --no-color
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

Example shape:

```text
timescale: 1 ns
range: 20..50 ticks
signals: 3
tick | time | top.clk | top.count [3:0] | top.stop
-----+------+---------+-----------------+---------
...
```

The raw `tick` column is the source-of-truth timestamp. The `time` column is an exact human-readable representation derived without floating-point arithmetic.

## Requirements

```text
Python >= 3.10
runtime dependencies: none outside the Python standard library
qualified userspace target: Linux
```

## Development checks

```bash
python3 -m unittest discover -s tests -v
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --dump --ascii --no-color
```

See `DESIGN.md` for the project contract, supported VCD subset, data model, exact time rules, TTY behavior, and milestones.
