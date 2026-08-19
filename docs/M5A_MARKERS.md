# M5a marker semantics

M5a adds two persistent temporal markers on top of the completed course core. Markers are an optional inspection aid; they do not change parsing, signal selection, exact-time rules, `--dump`, or qualification behavior.

## Marker state

Each marker stores only one exact raw VCD tick:

```text
A: Optional[int]
B: Optional[int]
```

No signal values are copied into marker state. This keeps the VCD model as the source of truth and prevents stale snapshots when the displayed signal set changes.

## Controls

```text
m    place or move marker A to the cursor
M    place or move marker B to the cursor
c    clear both markers
```

Placing a marker again simply moves it to the current exact cursor tick.

## Snapshot semantics

The marker table is derived from the signals currently selected for display. For each marker and signal:

```text
marker value = signal.stream.value_at(marker_tick)
```

Therefore the value is the post-change value at that VCD timestamp, using the same semantics as the normal value-at-cursor column. Changing signal checkboxes immediately changes the table columns; the marker itself remains only a timestamp.

## Delta time

When both markers exist:

```text
delta ticks = B - A
```

The result is signed. B may be before A, and coincident markers produce zero. Physical-time formatting uses the existing exact `TimeScale` model; floating-point arithmetic is never introduced.

## Presentation

A and B are shown on the time ruler and as non-destructive attributes on waveform cells. The underlying waveform glyph is preserved, including `/`, `\`, and bus-value characters. The cursor is rendered last and therefore has visual precedence when it shares a terminal cell with a marker.

The marker table below the waveform is authoritative when terminal-column quantization causes A, B, or the cursor to overlap visually. The table is width-bounded and includes only as many selected-signal columns as fit.

With no markers, the marker panel consumes no screen space. With one marker, the missing marker and delta are shown as unset rather than inferred.

## Scope boundary

M5a is the first post-course-core capability. It intentionally stops at two markers, snapshots, and exact delta-time measurement. It does not add configuration, mouse interaction, command mode, session persistence, or large-file indexing.
