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
Space               show/hide the focused signal, or every signal in a scope
a, Ctrl+A           show all signals, or hide all when all are shown
A                   hide all signals
v                   vector format menu (Up/Down, Enter, Esc)

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

## Selecting signals

`--signals` (`-s`) takes comma-separated selectors and may be repeated, so a long
selection can be split across lines. Each selector is resolved in tiers, narrowest
first:

```text
tb.dut4.clk     the whole name, with or without its [msb:lsb] range
dut4.clk        a trailing run of scopes, anchored at a "."
clk             a leaf name: the top-level clk if there is one, else every clk
tb.dut?.value   a glob, when the selector contains * or ?
in              a substring, only when nothing above matched
```

A selector that matches more than one signal is accepted — every clock in a
design is a reasonable thing to ask for — but it says so, and names the paths
that would have narrowed it:

```text
$ vcdtui counter.vcd --signals clk --dump
vcdtui: warning: 'clk' matched 3 signals; select one with its path:
  tb_counter.clk
  tb_counter.dut4.clk
  tb_counter.dut8.clk
```

`--list` prints every full path, one per line, and `--find PATTERN` prints the
matching ones. Both are pasteable straight back into `--signals`.

### Globs

Globs follow the shell convention with `.` as the separator: `*` and `?` stay
inside one hierarchy level, `**` crosses levels. Quote them, or the shell will
expand them first.

```bash
vcdtui counter.vcd -s 'tb_counter.*'      # the signals directly in tb_counter
vcdtui counter.vcd -s 'tb_counter.**'     # everything below it as well
vcdtui counter.vcd -s '**.clk'            # every clk in the design
vcdtui counter.vcd -s 'dut?.value'        # value in dut4 and in dut8
```

A glob is matched from the root first, so `*.clk` is the `clk` one level down and
not every `clk` in the design. Only if nothing matches there is the pattern
retried at each scope boundary, which is what lets `dut?.value` work without
naming the testbench. `*` and `?` are the only special characters, so a declared
bit range can be typed out: `-s '**.value[7:0]'`.

Unlike a bare leaf name, a glob is a deliberate request for a set of signals, so
matching several of them is not reported as ambiguous.

### Working inside one instance

`--scope PATH` roots the whole view at one scope: selectors resolve inside it,
and `--list`, `--find` and `--dump` name signals relative to it.

```bash
vcdtui counter.vcd --scope tb_counter -s clk,start,dec,in4,value4,stop4
```

Each name now means one signal, so nothing is ambiguous and nothing has to be
spelled out twice. In a Makefile the same selection reads better one per line:

```make
VCDTUI_ARGS = --scope tb_counter \
              -s clk -s start -s dec \
              -s in4 -s value4 -s stop4
```
 `--scope` must name exactly one scope; if a name like
`regfile` exists in two instances, vcdtui says so and lists both. Without
`--scope`, names are printed in full exactly as before.

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

The compatibility target is the VCD emitted by Icarus Verilog 12.0, and CI opens
a trace that Icarus actually wrote on every run.

```text
nested scopes, aliases, multiline directives, opaque identifier codes
scalar 0/1/x/z and binary vectors, normalized to the declared width
real and string values, kept verbatim and never radix-converted
$comment anywhere, in the header and between value changes
$dumpvars, $dumpall, $dumpoff, $dumpon, parsed rather than skipped
declared bit ranges kept out of the signal name
exact integer/rational timescale handling
```

A trace whose value changes simply stop is recovered with a warning rather than
rejected, which is what a simulation killed part way through leaves behind.
Extended VCD (EVCD) and other extensions are named in the error instead of being
guessed at.

Hand-readable traces live in `examples/qualification/`: normal ones at the top
level, `generated/` captured from a real Icarus run, `truncated/` for recovery,
and `malformed/` for clean failure. Every one of them is exercised by the test
suite.

See `DESIGN.md` for the exact parser contract, `CHANGELOG.md` for what changed between releases, and `docs/` for focused interaction notes.

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

CI runs the suite on Python 3.10 through 3.13, asserts that `vcdtui.py` imports
nothing outside the standard library and still runs under `env -i`, and then
simulates a design with Icarus Verilog 12.0 and opens the trace it produces.
That last job is the point: a viewer that passes its own tests but cannot read
what the simulator actually writes is not working.
