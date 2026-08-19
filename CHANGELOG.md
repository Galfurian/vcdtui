# Changelog

## 0.3.0

Selecting signals in a testbench that instantiates the same module twice took
either a leaf name that swept up every copy or an instance path for every
signal: six signals cost 96 characters. This release is about naming a selection
in a way that fits on a slide.

### Signal selection

- `--scope PATH` roots the whole view at one scope. Selectors resolve inside it
  and `--list`, `--find`, `--dump` and the tree name signals relative to it, so
  `--scope tb_counter -s clk,start,dec` means three specific signals. A scope
  that matches more than one place is an error listing the candidates, because a
  view has one root and guessing would show the wrong instance. Names are
  stripped only when `--scope` is passed, so default `--dump` output is
  unchanged.
- Glob selectors, with the shell convention and `.` as the separator: `*` and
  `?` stay inside one hierarchy level, `**` crosses levels. `-s 'tb.*'`,
  `-s 'tb.**'`, `-s '**.clk'`, `-s 'dut?.value'`. Only `*` and `?` are special,
  so `-s '**.value[7:0]'` selects by declared bit range. A glob is matched from
  the root first and only retried at each scope boundary if nothing matched
  there, which keeps `*` and `**` distinct. Matching several signals is not
  reported as ambiguous for a glob: that is what it asked for.
- A selector that is exactly a signal's name now wins over one that is a
  trailing run of its scopes, so `clk` is the top-level `clk` when the design
  has one rather than every `clk` in it.
- `--signals` / `-s` is repeatable, so a long selection can be written one
  selector per line instead of as one comma-separated string.
- The resolution order is documented: whole name, then path, then glob, then
  substring, each tier used only when the previous finds nothing.

### Qualification

- The Icarus Verilog job now simulates a design that instantiates one module
  twice and checks the ambiguity warning, `--scope`, the `*` versus `**`
  distinction and `dut?.value` against the trace Icarus actually wrote.
- 247 tests, up from 198.

## 0.2.0

The 0.1.0 parser could not open a single trace produced by Icarus Verilog 12.0,
its own stated compatibility target. This release fixes that and hardens the
rest of the tool around it.

### VCD compatibility

- Accept `$comment` after `$enddefinitions`, and parse `$dumpvars`, `$dumpall`,
  `$dumpoff` and `$dumpon` as value-change blocks rather than rejecting them.
  Icarus writes `$comment` and `$dumpall` before the first timestamp, so every
  trace it produced failed with `unsupported value-change directive $comment`.
  Block bodies are parsed, not skipped: `$dumpall` and `$dumpon` carry real
  state and `$dumpoff` carries the all-`x` checkpoint.
- Support `real` and `string` value changes. A Verilog `real` is declared
  `$var real 1 <id>`, and `$dumpoff` writes `rNaN` for it, so any design
  containing one was unopenable. Such values are stored verbatim and skip width
  normalization, radix conversion, `x`/`z` coloring, edge detection and scalar
  waveform drawing.
- Keep the declared bit range out of the signal name. `$var reg 8 " count [7:0]`
  produced the name `top.count [7:0]`, which no exact selector could match, so
  `--signals count` fell through to substring matching and over-selected.
- Accept a vector wider than its declaration when the excess is redundant
  extension, since nothing is lost by dropping it.
- Recognise extended VCD (EVCD) and name it, instead of failing one token at a
  time on a grammar it does not follow.

### Resilience

- Recover the readable part of a truncated trace instead of rejecting the file.
  Everything before the cut is kept and reported as a warning.
- Stream the input rather than splitting the whole file into a token list. Peak
  memory on a 10 MB trace drops from 287 MB to 146 MB at the same speed.
- Report the line of every parse error, and the file it came from.
- Tolerate a byte order mark and undecodable bytes; reject non-VCD input up
  front by its first token.
- Exit 130 on Ctrl-C and 141 on a closed pipe, both without a traceback and
  without the interpreter's own shutdown noise.
- Check the interpreter version above the first construct that needs 3.10.

### Interface

- Resolve `--signals` selectors as a path first and only then as a substring, so
  `dut4.clk` names one signal. Report the matched paths when a selector is
  ambiguous.
- `v` opens a value-format menu with a cursor on the format in use, replacing
  the `[b] [x] [u] [s]` letter keys.
- `Space` is the only toggle; on a scope it shows or hides the whole group.
  `Enter` only expands and collapses.
- `a` and `Ctrl+A` toggle all signals; `A` still hides them all.
- Accept fractional physical times such as `--from 1.5us`, still exactly.

### Qualification

- CI runs the suite on Python 3.10 through 3.13, refuses any import outside the
  standard library, checks the script runs under `env -i`, and simulates a
  design with Icarus Verilog 12.0 before opening the trace it wrote.
- `examples/qualification/` is now exercised by the test suite, which had let it
  drift out of date.
- 198 tests, up from 52.

## 0.1.0

First release.
