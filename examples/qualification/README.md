# Qualification VCD corpus

These traces are intentionally small and hand-readable. Each file stresses one
VCD property rather than combining every corner case into a single fixture.

`tests/test_qualification_corpus.py` walks this directory and asserts that every
file behaves as the directory it lives in claims, including that it is listed
here. A corpus nothing exercises drifts out of date silently.

## Supported

Parse cleanly, with no warnings.

- `nested_scopes.vcd`: deep scope hierarchy and repeated short signal names.
- `aliases.vcd`: distinct `$var` declarations sharing one identifier code/stream.
- `weird_identifiers.vcd`: opaque punctuation-heavy identifier codes and unusual references.
- `xz_vectors.vcd`: scalar/vector `x` and `z`, including short-vector normalization cases.
- `sparse_initialization.vcd`: signals whose first value appears after time zero.
- `exact_times.vcd`: `10 ps` timescale with non-round raw timestamps.
- `real_values.vcd`: `real` and `string` value changes, including `rNaN` in a `$dumpoff` checkpoint.
- `showcase.vcd`: richer interactive trace for tree browsing, pan/zoom, markers, edges, and vector display formats.

## `generated/`

Captured from a real simulator run rather than written by hand. The `$date` line
is replaced by a `$comment` so the fixture is reproducible.

- `icarus12_dump_control.vcd`: Icarus Verilog 12.0, the qualified simulation
  baseline. Carries `$comment` and `$dumpall` before the first timestamp,
  `$dumpoff`/`$dumpon` checkpoints, a `real` declared as width 1, an `event`, an
  `integer`, a `parameter`, declared bit ranges written as separate tokens, and
  an identifier code aliased across two scopes.

## `truncated/`

Recovered, not rejected: everything before the cut is kept and one warning is
reported.

- `unterminated_dumpvars.vcd`: a `$dumpvars` block the writer never closed.
- `cut_mid_vector.vcd`: value changes that stop part way through a vector.

## `malformed/`

Deliberately rejected. These are examples of clean failure behavior, not
features to support. Each must fail with a `VCDParseError` naming the file and
the line.

- `alias_width_mismatch.vcd`: one identifier code declared at two widths.
- `timestamp_backwards.vcd`: a timestamp earlier than the one before it.
- `vector_overflow.vcd`: a vector value whose significant bits exceed the declaration.
- `evcd_ports.vcd`: an extended VCD, which is a different format.
- `not_a_vcd.vcd`: Verilog source passed by mistake.
