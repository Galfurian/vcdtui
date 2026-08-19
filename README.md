# vcdtui

`vcdtui` is a terminal-first VCD waveform viewer written in Python using only the standard library.

The project is designed to make digital simulation traces easy to inspect from a shell, over SSH, inside teaching environments, and anywhere a graphical waveform viewer is inconvenient.

## Goals

- Python 3.11+
- standard library only at runtime
- interactive terminal UI with color
- clear command-line interface built with `argparse`
- useful non-interactive output for scripts and teaching material
- readable implementation that can itself be studied

## Current status

The repository is at the initial scaffold stage. The command-line interface exists and the implementation is being built incrementally.

## Run

```bash
python3 vcdtui.py --help
python3 vcdtui.py examples/counter.vcd
```

Planned command-line workflows include:

```bash
python3 vcdtui.py trace.vcd --list
python3 vcdtui.py trace.vcd --find count
python3 vcdtui.py trace.vcd --signals clk,start,dec,count,stop --dump
python3 vcdtui.py trace.vcd --from 100ns --to 250ns --dump
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Project direction

See [DESIGN.md](DESIGN.md) for the intended behavior, user interface, data model, supported VCD features, and staged roadmap.

## License

MIT.
