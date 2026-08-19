# UI help and chrome polish

This refinement keeps the waveform area visually dominant and moves guidance to the places where it is useful.

## Top chrome

The top of the terminal contains only the compact `vcdtui` cursor/view title and the two-row time ruler. The persistent dim shortcut sentence previously shown above the ruler is removed.

## Bottom shortcuts

A short, width-aware hint bar is centered above the status line. Wide terminals show the most useful everyday controls; narrower terminals progressively reduce the list while keeping help and quit discoverable.

Unicode mode uses compact arrow glyphs and middle-dot separators. ASCII mode uses ASCII-only equivalents.

## Full help

`F1` and `?` open the complete control reference in a centered `curses` panel over the current waveform view. Pressing any key closes the panel and returns to the normal view.

`h` remains the left-cursor alias and is deliberately not repurposed for help.

The help content is compact enough to fit completely in a conventional 80x24 terminal while remaining centered. The window still clamps to smaller terminal dimensions and falls back gracefully if a terminal cannot allocate the centered subwindow.
