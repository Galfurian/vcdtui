# vcdtui

A small terminal-oriented VCD inspection tool written in Python using only the standard library.

The project targets Python 3.10+ and is designed around two equally important interfaces:

- deterministic command-line inspection suitable for scripts and qualification;
- an interactive terminal waveform view for temporal exploration.

## Status

The project is under active construction.

Milestone 1 currently focuses on the VCD parser and non-interactive signal queries. Waveform dumping and the interactive UI are intentionally staged later so they can be built on a tested data model.

## Current commands

```bash
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py --version
```

`--dump` is reserved for Milestone 2. Interactive mode is reserved for Milestone 3.

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
```

See `DESIGN.md` for the project contract, supported VCD subset, data model, exact time rules, TTY behavior, and milestones.
