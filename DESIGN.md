# vcdtui design

## Purpose

`vcdtui` is a small, self-contained VCD inspection tool for the terminal.

Its primary job is to make temporal behavior visible with as little setup as possible. A user should be able to point it at a VCD file and immediately inspect signals, move through time, select the signals that matter, and examine value changes around interesting events.

The implementation should remain simple enough to read, teach, modify, and carry into constrained environments.

## Core principles

### Standard library only

The program targets Python 3.11+ and has no runtime dependencies outside the Python standard library.

This is a deliberate design constraint. A fresh Python installation on a supported Unix-like environment should be enough to run the program.

The expected building blocks are:

- `argparse` for the command-line interface
- `bisect` for locating transitions efficiently
- `curses` for the interactive terminal interface
- `dataclasses` for the internal model
- `pathlib` for paths
- `re` for parsing and matching
- `typing` for readable interfaces
- `tomllib` only if configuration files are introduced later

### Terminal first

The interactive interface should work well in an ordinary terminal. It must not require special icon fonts.

Unicode box-drawing and block characters may be used when available, with an ASCII fallback for conservative terminals and captured output.

### Useful without the TUI

The VCD parser and data model must not depend on the interactive interface.

The same executable should support both interactive inspection and non-interactive queries suitable for scripts, examples, tests, and course material.

### Time is the primary axis

The program should preserve actual VCD timestamps rather than treating the trace as a dense array of equally spaced samples.

Signals should be represented as sparse streams of value changes. Navigation, rendering, edge finding, and inspection should operate on those transitions.

### Readability over cleverness

The code should favor explicit data structures and straightforward algorithms. The project is intended to be useful software, but also software that a student can reasonably open and understand.

## Supported VCD model

The first useful version should understand the common subset required for digital RTL simulation traces:

- `$timescale`
- nested `$scope` / `$upscope`
- `$var` declarations
- `$enddefinitions`
- timestamp records such as `#120`
- scalar changes: `0`, `1`, `x`, `z`
- vector changes such as `b0011`
- initial values in dump sections

Values should preserve unknown and high-impedance states rather than coercing them to integers.

The parser should tolerate ordinary whitespace and identifiers produced by common simulators. Unsupported constructs should fail clearly or be skipped deliberately; they should not silently corrupt the trace.

## Internal data model

A signal has metadata and a sparse transition stream.

Conceptually:

```text
Signal
  full_name
  width
  identifier
  changes
    times:  [0, 10, 30, 45, ...]
    values: [0,  1,  0,  1, ...]
```

The timestamp array remains sorted because the VCD stream is chronological. Operations such as "value at time", "next change", and "previous change" can therefore use binary search.

A hierarchy of scopes is retained separately so the interactive signal browser can present the same structure as the trace.

## Command-line interface

`argparse` is the public front door of the program. `python3 vcdtui.py --help` should provide useful documentation without requiring a separate manual.

The intended commands/options include:

```text
vcdtui.py FILE
vcdtui.py FILE --list
vcdtui.py FILE --find PATTERN
vcdtui.py FILE --signals PATTERN[,PATTERN...]
vcdtui.py FILE --from TIME
vcdtui.py FILE --to TIME
vcdtui.py FILE --dump
vcdtui.py FILE --ascii
vcdtui.py FILE --no-color
```

### `--list`

Print the available signal names and exit.

### `--find PATTERN`

Print signals whose full names match the query. Initial matching can be case-insensitive substring matching. More forgiving matching may be added later without changing the basic command.

### `--signals`

Restrict the displayed signals. Short names should be convenient when unambiguous; full hierarchical names must always work.

### `--from` and `--to`

Restrict the visible time window. Human-friendly values such as `100ns`, `2us`, and raw VCD ticks should be accepted.

### `--dump`

Render a waveform view to stdout and exit instead of entering the interactive UI.

This mode should be suitable for terminal capture, documentation, pipes, and regression tests.

### `--ascii`

Avoid Unicode drawing characters.

### `--no-color`

Disable color even when the terminal supports it.

## Interactive interface

The default invocation opens the interactive terminal UI.

The screen is divided conceptually into:

```text
+----------------------+---------------------------------------------+
| signal browser       | waveform area                               |
|                      |                                             |
| scopes               | time ruler                                  |
| selected signals     | traces                                      |
| visibility toggles   | cursor / markers                            |
|                      |                                             |
+----------------------+---------------------------------------------+
| status / key hints / current time / values                         |
+--------------------------------------------------------------------+
```

The exact proportions should adapt to terminal size.

## Signal browser

The left pane presents nested scopes and signals.

Required interactions:

- move selection up/down
- expand/collapse scopes
- toggle individual signal visibility
- search by name
- add/remove matching signals without restarting the program

The user should be able to hide irrelevant internal signals quickly and focus on a small working set.

## Waveform rendering

### Scalar signals

Binary values should be visibly high or low, with transitions connecting them.

Unknown and high-impedance states must have distinct rendering and color.

### Vectors

Buses should be rendered as regions labelled with their current value rather than as one row per bit by default.

Hexadecimal is a useful default for wide vectors, while the value inspector can expose binary and unsigned forms.

### Colors

Colors are functional rather than decorative. A default palette should distinguish at least:

- normal scalar waveform
- vector value
- unknown (`X`)
- high impedance (`Z`)
- current selection/focus
- time cursor
- markers
- secondary UI text

The palette should remain legible on both dark and light terminal backgrounds by using terminal defaults where practical.

## Navigation

The baseline key map should support both arrow keys and a small set of mnemonic keys.

Planned operations:

- left/right: pan through time
- up/down: move among signals
- `+` / `-`: zoom in/out
- `0`: show the complete trace
- `/`: search signals
- `g`: go to a timestamp
- `Space` or `Enter`: toggle the selected signal, depending on focus
- `Tab`: change focus between browser and waveform
- `q`: quit
- `?`: show help

Key bindings should remain small and discoverable. The bottom status line should expose the most important actions.

## Cursor and event inspection

A movable time cursor is one of the core features.

At the cursor position, the program should be able to show the value of each visible signal and identify changes at that instant.

A focused inspector should make transitions explicit:

```text
Time: 230 ns

signal         before       after
clk               0           1
start             0           0
dec               1           1
count          0x1         0x0
stop              0           1
```

This view is intended to make registered behavior and edge-relative changes easy to reason about.

## Transition navigation

The program should support direct navigation between events rather than requiring manual panning.

Planned commands include:

- next transition of the selected signal
- previous transition
- next rising edge
- previous rising edge
- next falling edge
- previous falling edge

These operations are natural consequences of the sparse transition model and should remain efficient even for long traces.

## Markers and timing measurements

A later milestone adds two independent markers.

The status area should show their positions and difference:

```text
A = 120 ns    B = 145 ns    delta = 25 ns
```

Markers make it easy to measure periods, latencies, pulse widths, and distances between stimulus and response.

## Command mode

A compact command prompt may be added after the baseline TUI is stable.

Possible commands:

```text
:goto 120ns
:find count
:add stop
:hide clk
:zoom 4
```

This should complement direct key bindings, not replace them.

## Non-interactive rendering

`--dump` should share the same waveform formatting logic as the TUI where practical.

Example shape:

```text
                  100       110       120       130
clk        ____----____----____----____----
start      __________------________________
dec        __________________----__________
count      | 3 |      2      | 1 |    0   |
stop       __________________________------
```

Exact glyphs may differ between Unicode and ASCII modes.

Color should be enabled only when appropriate for the output destination and may always be disabled explicitly.

## Error handling

Errors should be concise and actionable.

Examples include:

- file not found
- malformed VCD declaration
- unsupported or malformed value change
- invalid time expression
- signal pattern matching nothing
- terminal too small for interactive mode

Normal errors should not produce Python tracebacks unless a debug mode is deliberately introduced.

## Performance expectations

The initial implementation should comfortably handle the relatively small and medium traces commonly produced during RTL development and teaching.

The first implementation may parse the complete file into memory, but it should store only transitions rather than materializing every signal value at every timestamp.

If larger files become important, the architecture should allow later indexing or `mmap`-based access without changing the user interface.

## Testing strategy

Tests use only `unittest` and other standard-library modules.

The suite should cover:

- header parsing
- nested scopes
- scalar transitions
- vector transitions
- `X` and `Z`
- timescale conversion
- value lookup at arbitrary times
- next/previous transition lookup
- time expression parsing
- signal matching
- CLI argument validation
- deterministic plain-text waveform rendering

Small VCD fixtures should live in `examples/` or dedicated test fixtures and remain readable by hand.

## Repository shape

The project begins intentionally small:

```text
vcdtui/
  vcdtui.py
  README.md
  DESIGN.md
  LICENSE
  examples/
    counter.vcd
  tests/
    test_cli.py
```

The single-file implementation is a feature during early development. If the source grows enough that separation improves readability, it can later be split into a small package without changing the command-line experience.

## Milestones

### Milestone 0: scaffold

- repository structure
- `argparse` CLI
- project documentation
- example VCD
- standard-library test harness

### Milestone 1: parser and queries

- declarations and scope hierarchy
- timescale
- sparse scalar/vector transitions
- `--list`
- `--find`
- time parsing

### Milestone 2: static waveform output

- signal selection
- time window selection
- Unicode renderer
- ASCII renderer
- color/no-color behavior
- `--dump`

### Milestone 3: interactive TUI

- curses startup/shutdown
- panes and responsive layout
- signal browser
- visibility toggles
- pan and zoom
- colors
- help overlay

### Milestone 4: temporal inspection

- cursor
- value-at-time display
- before/after inspector
- next/previous transition
- rising/falling edge navigation
- goto time

### Milestone 5: measurement and polish

- dual markers and delta measurement
- command prompt
- optional configuration
- performance work for larger traces

## Non-goals for the initial releases

The first releases do not aim to implement every VCD extension or every workflow surrounding digital simulation.

They also do not require plugin systems, external themes, persistent project databases, or a packaging ecosystem simply to run the viewer.

The defining constraint remains simple: one Python program, a VCD file, and a terminal should be enough to inspect a waveform effectively.
