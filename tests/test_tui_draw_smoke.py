"""Draw a whole frame into a recording stub instead of a terminal.

The rendering helpers are pure and tested directly, but nothing checked that
_draw_tui wires them together: whether the dense glyph and its count actually
reach the screen, and at which zoom.
"""

import collections
import unittest

import vcdtui

from tests.test_interval_rendering import clock_trace


class RecordingScreen:
    """The handful of curses window methods the draw path uses."""

    def __init__(self, height=30, width=120):
        self.height, self.width = height, width
        self.rows = [[" "] * width for _ in range(height)]

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.rows = [[" "] * self.width for _ in range(self.height)]

    def addstr(self, y, x, text, attr=0):
        if not 0 <= y < self.height:
            raise ValueError("row out of range")
        for offset, char in enumerate(text):
            if 0 <= x + offset < self.width:
                self.rows[y][x + offset] = char

    def refresh(self):
        pass

    def move(self, y, x):
        pass

    def clrtoeol(self):
        pass

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.rows)


def draw(vcd, signals, view_start, view_end, *, ascii_only=False, height=30, width=120):
    state = vcdtui.TUIState(
        cursor=view_start,
        view_start=view_start,
        view_end=view_end,
        selected=[True] * len(signals),
        expanded_scopes={("tb",)},
        display_formats=["binary"] * len(signals),
    )
    screen = RecordingScreen(height, width)
    vcdtui._draw_tui(
        screen,
        vcd,
        signals,
        0,
        vcd.last_time,
        state,
        ascii_only=ascii_only,
        # Every attribute is plain, so the recorded frame is the text itself.
        attrs=collections.defaultdict(int),
    )
    return screen.text()


class DrawSmokeTests(unittest.TestCase):
    def setUp(self):
        self.vcd = clock_trace(5, 2000)
        self.signals = self.vcd.signals

    def test_a_frame_draws_without_raising(self):
        self.assertIn("vcdtui", draw(self.vcd, self.signals, 0, 2000))

    def test_a_dense_view_shows_the_glyph_and_its_count(self):
        frame = draw(self.vcd, self.signals, 0, 2000)
        self.assertIn("▓", frame)
        self.assertRegex(frame, r"▓ \d+ changes in this column")

    def test_the_ascii_frame_uses_the_ascii_glyph(self):
        frame = draw(self.vcd, self.signals, 0, 2000, ascii_only=True)
        self.assertIn("#", frame)
        self.assertRegex(frame, r"# \d+ changes in this column")
        self.assertNotIn("▓", frame)

    def test_a_resolvable_view_shows_no_dense_glyph_and_no_count(self):
        frame = draw(self.vcd, self.signals, 0, 60)
        self.assertNotIn("▓", frame)
        self.assertNotIn("changes in this column", frame)

    def test_a_small_terminal_still_draws(self):
        self.assertIn("resize", draw(self.vcd, self.signals, 0, 2000, height=8, width=40))


if __name__ == "__main__":
    unittest.main()
