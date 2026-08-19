# vcdtui

A small, dependency-free VCD inspector for the terminal. `vcdtui` provides both a deterministic CLI path for scripts and a `curses` interface for interactive waveform exploration.

Requires Python 3.10+ and only the standard library.

## Quick start

```bash
python3 vcdtui.py examples/counter.vcd --list
python3 vcdtui.py examples/counter.vcd --find count
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop --dump --ascii --no-color
python3 vcdtui.py examples/counter.vcd --signals clk,count,stop
```

Time ranges accept raw VCD ticks or exact physical values:

```bash
python3 vcdtui.py examples/counter.vcd \
  --signals clk,count \
  --from 20ns --to 50ns \
  --dump --ascii --no-color
```

Physical times are never rounded: a value that does not land exactly on the VCD time grid is rejected.

## Interactive view

```text
signal tree | shown @cursor | waveform
```

The signal tree follows nested VCD scopes, the middle pane shows the exact value at the cursor, and the waveform pane provides an exact time ruler, pan/zoom, transition navigation, markers, and scalar/bus rendering.

Press `F1` or `?` for the full centered help. Common controls:

```text
Tab                 switch tree / waveform focus
Up/Down, j/k        move in the focused pane
Enter               expand/collapse scope
Space               show/hide signal
a, Ctrl+A           show all signals, or hide all when all are shown
A                   hide all signals
v                   vector format: bin / hex / unsigned / signed

Left/Right, h/l     move cursor one VCD tick
Home/End, 0/$       active-range start / end
g                   goto exact tick or physical time
< / >               pan
+ / -               zoom

n/N                 next / previous transition
e/E                 next / previous clean binary edge
r/R                 next / previous rising edge
f/F                 next / previous falling edge

m / M               place marker A / B
c                   clear markers
i                   before/after inspector
q                   quit
```

`Ctrl+Left` / `Ctrl+Right` are aliases for clean binary-edge navigation when the terminal exposes those modified keys; `e/E` is the portable form.

Vector display format is per signal. The underlying VCD value remains unchanged, and values containing `x` or `z` remain explicit bit patterns instead of being coerced to a number.

## Deterministic CLI

`--dump` emits a terminal-width-independent event matrix using the same parsed model and exact-time semantics as the TUI. Rows contain range boundaries and timestamps where selected streams change; values are post-change values at that timestamp.

Useful qualification path:

```bash
python3 vcdtui.py trace.vcd \
  --signals clk,count \
  --dump --ascii --no-color
```

`--list` and `--find` are also non-interactive. ANSI color is disabled automatically when output is redirected.

## VCD support

The current subset covers nested scopes, aliases, scalar `0/1/x/z`, binary vectors, sparse changes, multiline directives, unusual identifier codes, and exact timescale handling. Real/string values and unsupported extensions fail clearly rather than being guessed.

Hand-readable normal, awkward, and deliberately malformed traces live in `examples/qualification/`.

See `DESIGN.md` for the exact parser contract and `docs/` for focused interaction notes.

## Requirements

```text
Python >= 3.10
runtime dependencies: none outside the Python standard library
target: Linux
```

Interactive mode requires the standard-library `curses` module. Non-interactive commands do not initialize `curses` and remain usable in CI or redirected pipelines.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 vcdtui.py examples/qualification/showcase.vcd --list
python3 vcdtui.py examples/qualification/showcase.vcd --dump --ascii --no-color
```
