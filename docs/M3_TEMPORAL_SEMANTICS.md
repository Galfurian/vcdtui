
### M3 implemented temporal semantics

The M3 cursor is an exact VCD tick inside the active range. Cursor movement never introduces fractional time and `goto` uses the same exact `TimeScale.parse_ticks()` conversion used by non-interactive range selection.

The inspector has a deliberately strict definition:

```text
before(t) = last value with change timestamp < t
after(t)  = value after all changes with timestamp <= t have been applied
```

Therefore, at a timestamp containing a transition, `before` and `after` expose the transition itself. Between transition timestamps they are equal. At the beginning of a trace, `before` may be unknown while `after` contains the `$dumpvars` initialization.

These semantics live in pure model functions and are tested without `curses`. The TUI is only a presentation client.

The initial M3 waveform is intentionally a sampled state track rather than a full navigation engine. Scalar low/high states use low/high glyphs, vectors use a compact track, and X/Z remain explicit. The cursor is a separate overlay. Signal browsing, horizontal pan/zoom, and edge-to-edge navigation remain M4 responsibilities.

`curses` is imported lazily only after the interactive TTY guard passes. Parser/query/dump operation must continue to work even when interactive terminal initialization is unavailable.
