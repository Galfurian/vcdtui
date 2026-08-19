# vcdtui design

## Purpose

`vcdtui` is a small digital timing inspection tool for VCD traces. It is designed to make temporal evidence easy to inspect from a terminal, both interactively and non-interactively.

The project deliberately values a small, explainable implementation over breadth.

## Baseline contract

- Python 3.10 or newer.
- Python standard library only at runtime.
- Linux userspace is the qualified execution target.
- The normal interactive target is a Linux process attached to an ordinary host terminal, including a terminal attached to a container.
- Native Windows support is not a course-core requirement.
- No feature in the course core may require a package manager or a third-party Python package.

The program should remain runnable as:

```text
python3 vcdtui.py trace.vcd
```

## Core principles

1. **The parser is the source of truth.**
   The TUI and the deterministic stdout renderer are clients of the same parsed model.
2. **Non-interactive behavior is a first-class capability.**
   Parsing, time handling, signal selection, and rendering must be qualifiable without driving a terminal UI.
3. **VCD time is exact.**
   Raw timestamps are integers. Unit conversion uses integer or rational arithmetic and never floating point.
4. **Value changes are sparse.**
   A signal stream stores changes, not a value copied at every global timestamp.
5. **Names and value streams are distinct objects.**
   Multiple `$var` declarations may alias the same VCD identifier code and therefore the same transition stream.
6. **Unsupported input fails deliberately.**
   The initial parser supports a documented VCD subset rather than silently guessing.
7. **Expected failures are concise.**
   Normal user errors do not emit Python tracebacks. `--debug` enables tracebacks for development.

## Internal model

The model separates VCD identifier codes from hierarchical names.

```text
identifier code ──────> ValueStream
                         identifier
                         width
                         kind
                         changes[]

hierarchical name ────> Signal
                         full_name
                         reference
                         bit_range
                         width
                         var_type
                         stream ─────> ValueStream
```

Conceptually:

```text
Change
  time: int
  value: scalar/vector state

ValueStream
  identifier: str
  width: int
  kind: str          # bit | real | string
  changes: list[Change]

Signal
  full_name: str          # top.dut.count
  reference: str          # count
  bit_range: str          # [3:0], or empty
  width: int
  var_type: str
  stream: ValueStream

VCDFile
  timescale
  signals
  identifier -> ValueStream
  last_time
```

If the same identifier code is declared more than once, the declarations share one `ValueStream`. Incompatible widths for the same identifier are an error.

Identifier codes are treated as opaque non-whitespace strings. They must never be assumed to be numeric or alphanumeric.

### Names and declared bit ranges

A `$var` reference may carry a declared bit range, and the qualified baseline
writes it as a separate token:

```text
$var reg 8 " count [7:0] $end
$var reg 3 $ \mem[0] [2:0] $end
$var reg 1 # \escaped$name $end
```

The range is not part of the name. `full_name` and `reference` hold the name
alone, `bit_range` holds the range, and the display forms rejoin them without a
space:

```text
full_name          top.dut.count
display_name       top.dut.count[7:0]
reference          count
display_reference  count[7:0]
```

Names are what a selector matches, display forms are what the UI shows. A
selector matches `full_name`, `reference` or `display_name`, so both what
`--list` prints and what a table header shows can be pasted back into
`--signals`.

Brackets already present in the identifier token are only split off when they
are a `msb:lsb` range. A bare `[0]` there indexes an array element and belongs
to the name; splitting it would merge distinct elements into one.

A leading backslash only delimits an escaped identifier and is stripped, so
`\mem[0]` is selectable as `mem[0]`.

## Exact time model

VCD timestamps are stored as raw integer ticks.

The parsed timescale is represented exactly, for example:

```text
10 ps
```

A CLI time such as:

```text
1ns
```

is converted to ticks with integer/rational arithmetic (`fractions.Fraction` is sufficient). Floating-point arithmetic is not used.

Initial policy: if a requested physical time does not fall exactly on a VCD tick, reject it with a concise error rather than rounding.

Raw integer CLI times mean raw VCD ticks.

## Supported VCD subset: course core

The first qualified parser contract is intentionally narrow.

### Supported header/directive behavior

```text
$date          ignored safely
$version       ignored safely
$comment       ignored safely, in the header and in the value-change section
$timescale     parsed
$scope         parsed
$upscope       parsed
$var           parsed
$enddefinitions
$dumpvars      parsed as a value-change block
$dumpall       parsed as a value-change block
$dumpoff       parsed as a value-change block
$dumpon        parsed as a value-change block
```

A dump-control block is not skipped: its body uses the same value-change
grammar as the surrounding stream and is recorded at the timestamp currently in
effect. The qualified simulation baseline (Icarus Verilog 12.0) emits
`$comment` and `$dumpall` immediately after `$enddefinitions`, before the first
timestamp, so both must be accepted there.

### Supported value changes

```text
timestamps:        #123
scalar values:     0 1 x z
binary vectors:    b0101
real values:       r1.5
string values:     sIDLE
```

Upper/lower case `X/Z` is normalized.

Vectors are normalized to their declared width. Short binary values are zero-extended; short values beginning in `x` or `z` are extended with that state. Values wider than the declaration are rejected.

Real and string values are not bit vectors, so they are stored verbatim and are
never width-normalized, radix-converted or interpreted as `x`/`z`. A real value
is validated as a number and kept in its original textual form, which preserves
what the writer emitted, including `NaN` and `Inf`. The qualified simulation
baseline declares a Verilog `real` as `$var real 1 <id> <ref> $end` and writes
`rNaN` for it inside the `$dumpoff` checkpoint.

Each `ValueStream` therefore carries a value `kind`:

```text
bit      0/1/x/z scalars and b... vectors
real     r... values
string   s... values
```

The kind comes from the `$var` type. A `r`/`s` value on a variable declared with
a generic type is unambiguous, so it adopts that kind instead of failing; a value
form that contradicts state already recorded for the stream is an error. Only
`bit` streams participate in edge detection and waveform drawing; the other kinds
render as labelled bus tracks.

### Explicitly unsupported initially

```text
analog extensions
non-standard/exotic VCD extensions
```

Unsupported constructs should produce a clear error identifying the construct.

### Parser robustness requirements

- directives may span lines;
- parsing must not depend on line-oriented `$var` declarations;
- `$var ... $end` is tokenized until its terminating `$end`;
- identifier codes are opaque strings;
- nested scopes use a real stack;
- `$dumpvars ... $end` and the other dump-control blocks are handled explicitly;
- repeated changes at one timestamp resolve deterministically to the last value seen;
- timestamps must be nondecreasing;
- malformed scope nesting is rejected;
- unusual/escaped references must not crash the parser.

The core compatibility target is the VCD emitted by the qualified simulation baseline. Expanding the subset is allowed only with tests.

## CLI contract

The CLI uses `argparse` and should be useful independently of the TUI.

Course-core commands include:

```text
vcdtui trace.vcd
vcdtui trace.vcd --list
vcdtui trace.vcd --find count
vcdtui trace.vcd --signals clk,start,dec,value,stop --dump
vcdtui trace.vcd --from 100ns --to 250ns --dump
vcdtui --version
```

Planned options:

```text
--list
--find PATTERN
-s, --signals PATTERN
--from TIME
--to TIME
--dump
--ascii
--no-color
--version
--debug
```

`--debug` is the only normal mode in which Python tracebacks should be shown.

## Deterministic stdout renderer

`--dump` is a primary interface, not a degraded fallback.

It must be suitable for:

- qualification checks;
- CI;
- examples in course material;
- piping/redirection;
- terminals where curses is unavailable or undesirable;
- reproducible snapshots.

`--ascii --no-color` must provide stable, terminal-independent output.

The renderer and TUI must consume the same selected signals and same time model.

## Interactive TTY behavior

Interactive mode requires a usable TTY.

Before initializing curses, the program checks that stdin and stdout are attached to a terminal. If not, it exits cleanly with a message that suggests `--dump`.

The program must not expose errors such as `setupterm` tracebacks during normal use.

## TUI course core

The minimum complete interactive interface contains:

```text
signal selection
pan
zoom
cursor
goto time
next / previous transition
next / previous rising edge
next / previous falling edge
value before / after cursor
```

Color is part of the normal UI, with graceful fallback when colors are unavailable or disabled.

Suggested semantic use:

```text
valid scalar waveform   green
vectors                 cyan
X                       red
Z                       magenta
cursor                  yellow
selected signal         bold/reverse
secondary UI            dim/gray where supported
```

The TUI must not require special fonts. Ordinary Unicode box/wave characters are acceptable, with an ASCII fallback.

## Temporal inspection

Temporal inspection is a core teaching capability, not post-processing polish.

Given a cursor time, the UI should be able to show a compact before/after table:

```text
              before    after
start            0         1
dec              1         1
value            1         0
stop             0         1
```

Navigation should make these operations direct:

```text
next/previous transition of selected signal
next/previous rising edge
next/previous falling edge
```

The semantics of "before" and "after" must be defined against VCD timestamps and tested. The UI reports evidence from the trace; it does not infer RTL intent.

## Search and signal selection

The first implementation may use deterministic case-insensitive substring search. A third-party fuzzy matching package is not permitted.

Hierarchical signal names should remain visible so similarly named signals in different scopes are distinguishable.

Aliases remain distinct selectable `Signal` objects while sharing one `ValueStream` internally.

## Errors

Expected failures include:

- missing file;
- malformed VCD;
- unsupported VCD construct;
- invalid time specification;
- physical time not aligned to an exact VCD tick;
- interactive mode without a TTY;
- unavailable requested signal.

Normal output format:

```text
vcdtui: error: concise explanation
```

No traceback unless `--debug` is active.

## Testing and qualification

Tests use the Python standard library (`unittest`).

The course-core behavior must be testable without curses. In particular, qualification should be able to:

```text
generate/read a tiny VCD
run --list
run --find
run --signals ... --dump --ascii --no-color
verify expected signal names, timestamps, and values
```

The TUI may have separate/manual qualification. Automated qualification must not require simulating terminal keystrokes.

Fixtures should cover at least:

- scalar changes;
- vectors;
- x/z states;
- nested scopes;
- aliases sharing an identifier code;
- unusual identifier codes;
- `$dumpvars` initialization;
- multiline directives;
- exact and non-exact physical time conversion;
- malformed/unsupported input with clean errors.

## Milestones

### M1 — foundations: parser and queries

- Python 3.10+ baseline;
- internal `ValueStream` / `Signal` alias model;
- exact timescale representation;
- supported-subset parser;
- `--list`;
- `--find`;
- `--version`;
- `--debug`;
- clean error behavior;
- parser/query tests.

### M2 — deterministic dump

- signal selection;
- exact `--from` / `--to` ranges;
- scalar and vector stdout rendering;
- `--ascii`;
- `--no-color`;
- deterministic snapshots suitable for qualification.

### M3 — minimal TUI plus temporal inspection

- curses lifecycle and TTY guard;
- color pairs and fallback;
- minimal waveform display;
- cursor;
- goto;
- before/after value inspection.

### M4 — complete course-core navigation

- signal browser/selection;
- pan and zoom;
- next/previous transition;
- next/previous rising edge;
- next/previous falling edge;
- help/status UI;
- robust resize behavior.

## COURSE CORE COMPLETE

M1 through M4 define the target capability that may be qualified as part of the teaching toolchain. The project is allowed to stop here and remain complete for its primary purpose.

## Post-course-core features

These are intentionally outside the core scope and must not block M1–M4:

- dual markers and delta-time measurement;
- command prompt/mode;
- user configuration files;
- configurable keybindings;
- mouse interaction;
- memory mapping and indexing for very large traces;
- broader VCD extensions;
- additional search sophistication.

If configuration is added while Python 3.10 remains the baseline, it must not introduce a TOML dependency. Standard-library-only remains the stronger constraint.

## Performance direction

The initial model loads a trace into sparse Python structures. That is appropriate for small and medium instructional traces.

If large-file support later becomes necessary, indexing and `mmap` may be explored without changing the public model. This is post-course-core work.

## Definition of minimum complete

The non-interactive minimum is:

```text
vcdtui trace.vcd
vcdtui trace.vcd --list
vcdtui trace.vcd --find count
vcdtui trace.vcd --signals clk,start,dec,value,stop --dump
```

plus an interactive TUI supporting:

```text
select signals
pan
zoom
cursor
goto
next/previous transition
next/previous rising/falling edge
value before/after cursor
```

Anything beyond this should justify its complexity rather than expand the project by default.
