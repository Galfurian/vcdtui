# M6 taller tracks, vector bits, and stepping across changes

M6 grows the interactive view. It does not change the parser, the signal
model, `--dump`, `--dump-wave`, or the one-row track contract: a track at
height 1 renders byte-identically to before, which is what keeps the
deterministic snapshots and the existing tests meaningful.

## Taller tracks

`T` grows and `t` shrinks every waveform track, from 1 to 4 rows. A track
taller than one row is a block of rows followed by a blank separator, so
neighbouring tracks cannot merge into what would read as one waveform; the
wave pane's capacity is measured in these blocks.

The multi-row renderers classify columns with the same functions as the
one-row one (`_scalar_column_states`, `_bus_column_kinds`), so a taller track
shows the same transitions in the same columns rather than a second opinion
about where they land.

A scalar becomes a square wave:

```text
     ┌──┐     ┌──
  ───┘  └─────┘
```

The high level runs along the top row, the low level along the bottom one,
and an edge joins them vertically (`┌ ┐ └ ┘ │`). Under `--ascii`, two rows
draw the classic `_/ \_` shape and three or more use `|` for the verticals.
An x or z level has no level to draw, so it fills the whole column, as a
dense column fills it with `▓` (`#`).

A bus becomes a box: the held runs are segments with top and bottom borders,
boundaries join them with `┬`/`┴`, and the value sits centred in the middle
row. The label rule is unchanged - a label that does not fit its run is
omitted, never truncated. At two rows a bus keeps its one-line track and puts
the labels on their own row above it, so no information is lost at the
smallest step up.

## Vector bits

`Enter` on a vector in the signal tree expands it, as it already did for a
scope; `Space` on a listed bit shows or hides that bit as its own scalar
track, drawn under its vector. A bit survives its parent being hidden:
collapsing the vector to read its bits alone is a legitimate way to look at
it, so those bits move to the end in declaration order instead of
disappearing.

A bit is a derived signal. Its stream records a change only where that bit
actually moved, so edges, transitions and `Ctrl+←/→` on it mean what they
say, rather than repeating the parent vector's every change. Bits are built
once per bit and cached in the session state.

Bit names use the declared range: expanding `count[7:0]` yields `count[7]`
down to `count[0]`, most significant first, which is the order the value
string carries them in. Without a declared range the width numbers them.

`A` and a hiding `a` also hide shown bits, so "all signals hidden" means an
empty wave pane, not a pane of leftover bits.

## Ctrl+Left/Right on every signal

`Ctrl+←/→` steps across the previous/next clean binary edge of a scalar, and
across the previous/next value change of a vector - the same idea at vector
width, since a vector has no single edge to point at. Real and string tracks
report that they have nothing to step across. Expanded bits step like the
scalars they are.

When no step remains, the cursor is sent to the matching end of the active
range. Standing on the first rising edge, `Ctrl+←` now reaches the range
start; standing on the last edge, `Ctrl+→` reaches the range end. At the
boundary itself the status line says there is nothing left rather than moving.

`n/N` (transition), `e/E` (any edge), `r/R` and `f/F` (rising/falling) are
unchanged: binary-edge queries stay scalar, and `next_transition` already
worked for vectors.

## The viewport's last tick owns a block of columns

Found while looking at the taller tracks: a linear column cut starved the
viewport's final tick of any column, so the previous run's span was extended to
own it. A change landing on that tick was then drawn by the previous run's
owner and immediately contradicted by the columns after it - a rising edge with
the old low level running through it, `┌ │ │ ┘` floating on a low line - and
the cursor could not move onto the tick, so pressing right at the last-but-one
tick left the `^` standing still while the exact readout moved.

Zoomed in past one tick per column, the partition is now by tick: every tick,
the last one included, owns a whole block of columns. Runs, ownership and the
half-open closing of the final span are unchanged; only the starving is gone.

The ruler follows: in that regime it marks tick positions, so no closing mark
is forced onto the final column - past the final tick's own position it read
as one more tick, with the end label naming it, so a cursor correctly on the
last timestamp looked one short of a "40ns" sitting at the view's right edge.
The end label is centred on the final tick's own column, where its cursor is
drawn. Zoomed out, a column covers many ticks and the closing mark and its
right-edge label are unchanged.

