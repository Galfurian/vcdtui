# M4.1 waveform UI polish

M4.1 refines presentation and interaction without adding a new qualification capability. The parser, exact-time model, deterministic dump, temporal inspection, and navigation contracts remain unchanged.

## Main layout

The interactive view is organized as three aligned areas:

```text
signal tree | shown @cursor | waveform
```

The left pane contains the hierarchical scope/signal tree. The middle area contains only currently displayed signals and their exact value at the cursor. The right area contains their waveform history over the current viewport.

`Tab` switches keyboard focus between the signal tree and the displayed waveform list.

## Signal tree

Scopes are represented hierarchically rather than as a flat list. `Enter` expands or collapses the focused scope and does nothing else. Signals retain checkboxes, and `Space` toggles whether the focused signal is displayed.

`Space` on a scope toggles every signal at or below it: the group is shown, or hidden when all of it is already shown. Matching is per scope component, so `dut` does not collect the signals of `dut4` and `dut8`.

`Enter` and `Space` are deliberately not interchangeable. `Enter` shapes the tree, `Space` changes what is displayed. Having `Enter` also toggle a signal meant the same key did two unrelated things depending on what happened to be focused.

The tree controls visibility; the displayed waveform list controls temporal navigation for signals that are currently shown.

## Waveform drawing

Scalar states use `_` for low and `‾` for high in Unicode mode (`_` and `-` in ASCII mode). Clean sampled transitions are drawn explicitly:

```text
rising    ____/‾‾‾‾
falling   ‾‾‾‾\____
```

`x` and `z` remain explicit rather than being interpreted as binary edges.

Vector tracks show value labels directly on the trace when the visible interval has enough terminal columns. The `shown @cursor` column remains the authoritative exact value at the cursor even when a bus segment is too narrow to contain its label.

## Non-destructive cursor

The cursor is an exact raw VCD tick. Its terminal-column representation must never replace the waveform character under it.

The renderer first draws the real waveform glyph, including `/`, `\`, or a bus-label character. The cursor then redraws that same glyph with the cursor attribute (yellow/reverse/bold where available). This preserves waveform evidence while still making the cursor column visible.

## Inspector

The before/after inspector keeps the established temporal semantics but is hidden by default. `i` toggles it when detailed event inspection is useful. This leaves most vertical space available for waveform rows during normal browsing.

## Scope boundary

M4.1 is a presentation refinement of the completed course core. Marker A/B support remains a separate post-core milestone and is intentionally not part of this change.
