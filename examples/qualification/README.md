# Qualification VCD corpus

These traces are intentionally small and hand-readable. Each file stresses one VCD property rather than combining every corner case into a single fixture.

Supported examples:

- `nested_scopes.vcd`: deep scope hierarchy and repeated short signal names.
- `aliases.vcd`: distinct `$var` declarations sharing one identifier code/stream.
- `weird_identifiers.vcd`: opaque punctuation-heavy identifier codes and unusual references.
- `xz_vectors.vcd`: scalar/vector `x` and `z`, including short-vector normalization cases.
- `sparse_initialization.vcd`: signals whose first value appears after time zero.
- `exact_times.vcd`: `10 ps` timescale with non-round raw timestamps.
- `showcase.vcd`: richer interactive trace for tree browsing, pan/zoom, markers, edges, and vector display formats.

`malformed/` contains deliberately rejected inputs. They are examples of clean failure behavior, not features to support.

Generated simulator traces can be added later under `generated/` once the simulator versions used for qualification are pinned.
