# M4 course-core navigation semantics

Milestone 4 completes the course-core interactive capability without changing the parser or exact-time contracts established by earlier milestones.

## Signal browser

The browser lists hierarchical VCD signal names. The focused signal is independent of visibility: `Space` toggles whether that signal is rendered, while transition and edge navigation operate on the focused signal.

The initial visibility mask comes from the same `--signals` selection used by `--dump`. Without `--signals`, all signals begin visible.

## Cursor and viewport

The active range is fixed by exact `--from` / `--to` bounds. Inside it, the TUI maintains two separate concepts:

```text
cursor      one exact raw VCD tick
viewport    an inclusive [view_start, view_end] interval
```

Cursor motion and edge navigation are exact and never quantized to terminal columns. The waveform is only a sampled visual representation of the viewport.

Pan changes the viewport but not the cursor. Zoom changes the viewport around the cursor when the cursor is visible. If exact cursor navigation lands outside the viewport, the viewport recenters while preserving its span when possible.

## Transition navigation

`next transition` means the first stored change whose timestamp is strictly greater than the cursor. `previous transition` means the last stored change whose timestamp is strictly less than the cursor.

A change at the current cursor timestamp is therefore not returned again.

## Edge navigation

Edges are defined only for scalar streams:

```text
rising     previous stored value == 0 and new value == 1
falling    previous stored value == 1 and new value == 0
```

Transitions through `x` or `z` do not count as binary edges. Vector streams have no rising/falling-edge interpretation in the course core.

## Completion boundary

With M4 the course core contains:

```text
VCD parsing and exact times
signal queries
deterministic dump
interactive signal selection
cursor and goto
before/after inspection
pan and zoom
next/previous transition
next/previous rising edge
next/previous falling edge
help/status UI
resize-safe curses lifecycle
```

The project may stop here and remain complete for its primary teaching purpose. Markers, command mode, configuration, mouse interaction, and large-trace indexing remain explicitly post-core.
