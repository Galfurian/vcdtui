# Per-signal value formats

Vector signals keep their raw VCD bit strings in the parsed model. The interactive UI may choose a presentation format independently for each `Signal`.

Press `v` while a vector signal is focused to open the format menu:

```text
value format: count[7:0]

 * binary
 >   hexadecimal
     unsigned decimal
     signed decimal (two's complement)

 Up/Down choose   Enter apply   Esc cancel
```

The cursor starts on the format already in use, marked `*`, so `Enter` alone
changes nothing. `Up`/`Down` (or `j`/`k`) move it and wrap at both ends, `Enter`
applies, `Esc` cancels.

The menu is built by `value_format_menu_lines`, a pure function, so its contents
are qualified without simulating terminal keystrokes.

Signed display uses two's-complement interpretation at the signal's declared width. The VCD format itself does not carry signedness, so signed display is always an explicit user choice rather than an inferred property.

Scalar values remain `0`, `1`, `x`, or `z`.

If a vector contains `x` or `z`, the original normalized bit pattern is shown rather than inventing a numeric value. The same per-signal choice is used consistently by the value-at-cursor column, waveform interval labels, before/after inspector, and marker table.

Aliases share their underlying `ValueStream` but remain distinct `Signal` objects. Their display formats are therefore independent: two aliases of the same VCD identifier may intentionally be shown in different radices.
