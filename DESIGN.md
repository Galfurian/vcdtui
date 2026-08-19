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

Raw integer CLI times mean raw VCD ticks. A physical time may be fractional
(`1.5us`); it is parsed with `Fraction`, so it stays exact and is still rejected
when it does not land on a tick.

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

Vectors are normalized to their declared width. Short binary values are
zero-extended; short values beginning in `x` or `z` are extended with that
state. A value wider than the declaration is accepted when the excess is
redundant extension of what remains, because nothing is lost by dropping it:

```text
declared width 4
  b1010        -> 1010
  b1           -> 0001
  bx           -> xxxx
  b000001010   -> 1010      redundant zeros
  bxxxxxx      -> xxxx      redundant x extension
  b111110101   -> rejected  significant bits beyond the width
```

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
extended VCD (EVCD)
analog extensions
non-standard/exotic VCD extensions
```

Extended VCD is a different format rather than a dialect of this one: it records
port direction and drive strength instead of plain value changes. It is detected
by `$var port` or `$dumpports` and named in the error, instead of failing token
by token on a grammar it does not follow.

Unsupported constructs should produce a clear error identifying the construct.

### Parser robustness requirements

- the input is tokenized lazily, one line at a time, and never materialized as
  a token list: cost scales with the value changes a trace contains, not with
  its size on disk;
- every parse error names the line it was found on;
- decoding is forgiving (`utf-8-sig`, `errors="replace"`): a byte order mark or
  a stray non-UTF-8 byte in a `$comment` or `$date` must not make a trace
  unreadable;
- input that is not a VCD at all is rejected up front, by its first token,
  rather than through a confusing downstream token error;
- directives may span lines;
- parsing must not depend on line-oriented `$var` declarations;
- `$var ... $end` is tokenized until its terminating `$end`;
- identifier codes are opaque strings;
- nested scopes use a real stack;
- `$dumpvars ... $end` and the other dump-control blocks are handled explicitly;
- repeated changes at one timestamp resolve deterministically to the last value seen;
- timestamps must be nondecreasing;
- malformed scope nesting is rejected;
- a trace whose value changes simply stop is recovered rather than rejected;
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

Choices offered in a panel are made with a cursor rather than with mnemonic
letters. A letter key has to be memorized, collides with the main keymap, and
cannot show what is currently in effect; a cursor placed on the active entry
shows the current state, the alternatives, and how to move between them, all at
once. `Up`/`Down` move and wrap, `Enter` applies, `Esc` cancels.

Panel content is produced by pure functions returning lines, so it stays
qualifiable without simulating terminal keystrokes.

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

A selector resolves in tiers, narrowest first, each one used only when the
previous finds nothing:

```text
name       the whole name, or the whole name with its declared bit range
path       a trailing run of its scopes, anchored at a "."
glob       a hierarchical pattern, when the selector contains * or ?
substring  anywhere in the name
```

Anchoring is what makes `dut4.clk` mean the `clk` inside `dut4`, while `ut4.clk`
does not name a path at all. Ordering the tiers means a precise selector is never
widened: `clk` selects the top-level `clk` when the design has one, and every
`clk` in the design only when it does not.

`--signals` is repeatable and each value is comma-separated, so `-s clk -s value4`
and `-s clk,value4` name the same set. Selection order always follows the trace's
declaration order rather than the order the selectors were typed, which keeps
`--dump` columns stable no matter how the selection was spelled.

### Globs

Globs use the shell convention with `.` as the separator: `*` and `?` match
within one hierarchy level, `**` spans any number of levels including none.
Keeping the two distinct is the reason a glob is anchored at the root rather than
floated the way a path selector is; a pattern that matched at any depth on its
own would make `**` mean nothing.

```text
tb.*            the signals declared directly in tb
tb.**           everything below tb
**.clk          every clk, at any depth
tb.**.clk       tb.clk and every clk below it
dut?.value      one character inside a level, never across one
count*          no separator: a leaf at any depth, as in an unrooted gitignore
```

An anchored pattern that matches nothing is retried at every scope boundary, so
`dut?.value` still works without naming the testbench. The tiers report which one
matched, because a glob is a deliberate request for a set of signals and must not
produce the ambiguity warning that a bare leaf name does.

`fnmatch` is not used: its `*` crosses separators and its `[...]` is a character
class, which would make a declared bit range unquotable. The translation is a
per-segment walk into one `re` pattern, matched against the name with a trailing
separator so that `**` can carry its own and span zero scopes. A run of `**`
segments collapses to one, because each is a repeated group and nesting them
makes a failing match backtrack exponentially. Substring matching is not
attempted for a glob, so a pattern that matches nothing fails saying so.

### Rooting the view at a scope

`--scope PATH` restricts the trace to one scope and re-roots the names it
contains. It resolves like a selector, except that ambiguity is fatal, because a
view has exactly one root and guessing would silently show the wrong instance.

```text
vcdtui counter.vcd --scope tb_counter -s clk,start,in4
```

Re-rooting happens once, in `scoped_view`, which returns a `VCDFile` whose
signals share the original `ValueStream` objects. Everything downstream reads
`full_name`, so selection, `--list`, `--find`, `--dump` and the tree all agree on
the shorter names without threading a prefix through them.

Two consequences are deliberate. Inside a scope a leaf name usually resolves in
the first tier rather than the second, which is what turns six instance-qualified
selectors into six words. And the prefix is stripped only when `--scope` is
passed, so the default `--dump` output stays byte-stable for the toolchains that
consume it as qualification evidence.

A selector matching several signals is not an error: a testbench instantiating
one module twice has identically named leaves in every scope, and asking for all
of them is legitimate. It is rarely what was meant, though, so the matched paths
are reported on stderr. Naming them there teaches the paths at the moment the
ambiguity appears, which no separate listing command can do.

Aliases remain distinct selectable `Signal` objects while sharing one `ValueStream` internally.

## Process behavior

`vcdtui` is a single command with no runtime dependencies, so it must behave
like an ordinary Unix filter under ordinary Unix conditions:

```text
interpreter too old   concise message before any 3.10-only construct is reached
Ctrl-C                exit 130, no traceback
closed pipe           exit 141, no traceback, nothing on stderr
expected failure      exit 2, "vcdtui: error: ..."
```

`vcdtui trace.vcd --list | head` is normal use, not a crash: the reader closing
the pipe must not produce a `BrokenPipeError` traceback, nor the interpreter's
`Exception ignored in sys.stdout` noise at shutdown.

## Truncated traces

A simulation killed part way through leaves a VCD with a complete header and
value changes that stop mid-stream. Everything recorded up to that point is
still true, and it is usually the interesting part, so it is kept:

```text
vcdtui: warning: trace is truncated at line 56: unexpected end of file
```

The distinction is between *incomplete* and *malformed*. Only an unexpected end
of input is recoverable, and only after `$enddefinitions`:

```text
value changes stop mid-vector          recovered, warning
$dumpvars block never closed           recovered, warning
header cut before $enddefinitions      fatal: the identifier map is incomplete
$end with no dump block open           fatal: malformed, not incomplete
timestamp that is not a number         fatal: malformed, not incomplete
```

Warnings go to stderr, never to stdout, and never change the exit code: a
truncated trace is still a usable trace, and `--dump` output must stay pipeable.

## Errors

Parse errors carry their position, and the file name when one is known:

```text
vcdtui: error: trace.vcd: line 137: unsupported value-change directive $foo
```

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

Qualification is not only "the tests pass". Continuous integration also has to
answer the question the tests cannot ask themselves:

```text
unittest matrix      3.10 through 3.13
standard library     no import outside it; runs under env -i
simulator end to end  simulate with the qualified baseline, open the result
```

The last one is the one that matters. A viewer whose own tests pass but which
cannot read what the simulator actually writes is not working, and only a real
simulator run can tell the difference.

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

Two properties keep that affordable and must not regress:

- the tokenizer is lazy, so the file is never held in memory as tokens;
- `Change`, `ValueStream` and `Signal` use `__slots__`, because one `Change`
  exists per value change and a per-instance `__dict__` would dominate.

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
