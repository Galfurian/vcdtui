"""Where the cursor is drawn, against where its tick actually lives.

The waveform is a point sample: column c shows the value at one tick, given by
_sample_ticks. The cursor column has to agree with that sampling, or the cursor
appears next to a transition boundary while the value readout, which is exact,
already reports the value from the other side of it.
"""

import unittest

import vcdtui


# Deliberately mixed: zoomed out (a column spans many ticks), around 1:1, and
# zoomed in (many columns per tick).
VIEWPORTS = [
    (0, 40, 30),
    (0, 100, 40),
    (0, 1000, 80),
    (0, 120, 60),
    (0, 53, 17),
    (0, 5, 30),
    (10, 30, 21),
]


class CursorColumnTests(unittest.TestCase):
    def test_a_columns_own_tick_maps_back_to_that_column(self):
        for start, end, width in VIEWPORTS:
            ticks = vcdtui._sample_ticks(start, end, width)
            for column, tick in enumerate(ticks):
                # Zoomed in, several columns share one tick; the first of them
                # is the one that owns it, which is where a bus boundary goes.
                expected = ticks.index(tick)
                with self.subTest(view=(start, end, width), column=column):
                    self.assertEqual(
                        vcdtui._cursor_column(tick, start, end, width), expected
                    )

    def test_the_column_shows_the_tick_the_cursor_is_on_or_the_next_one(self):
        # Never an earlier tick: that is what made the cursor sit left of the
        # boundary while already reporting the new value.
        for start, end, width in VIEWPORTS:
            ticks = vcdtui._sample_ticks(start, end, width)
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertGreaterEqual(ticks[column], tick)

    def test_the_viewport_edges_map_to_the_edge_columns(self):
        for start, end, width in VIEWPORTS:
            with self.subTest(view=(start, end, width)):
                self.assertEqual(vcdtui._cursor_column(start, start, end, width), 0)
                self.assertEqual(
                    vcdtui._cursor_column(end, start, end, width), width - 1
                )

    def test_a_tick_outside_the_viewport_is_clamped(self):
        self.assertEqual(vcdtui._cursor_column(-5, 0, 40, 30), 0)
        self.assertEqual(vcdtui._cursor_column(999, 0, 40, 30), 29)

    def test_degenerate_viewports_do_not_raise(self):
        self.assertEqual(vcdtui._cursor_column(3, 0, 40, 1), 0)
        self.assertEqual(vcdtui._cursor_column(3, 0, 40, 0), 0)
        self.assertEqual(vcdtui._cursor_column(7, 7, 7, 20), 0)


class CursorMeetsBusBoundaryTests(unittest.TestCase):
    """The reported case: a 4-bit signal changing between two sampled ticks."""

    TEXT = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 4 ! value4 [3:0] $end
$upscope $end
$enddefinitions $end
#0
b0 !
#27
b11 !
"""

    def setUp(self):
        self.signal = vcdtui.parse_vcd_text(self.TEXT).signals[0]

    def test_the_cursor_sits_on_the_boundary_at_the_transition_tick(self):
        start, end, width = 0, 40, 30
        track = vcdtui.render_bus_track(
            self.signal, start, end, width, ascii_only=False
        )
        column = vcdtui._cursor_column(27, start, end, width)
        self.assertEqual(vcdtui.cursor_track_glyph(track, column), "│")

    def test_the_column_and_the_value_readout_agree_across_the_transition(self):
        start, end, width = 0, 40, 30
        ticks = vcdtui._sample_ticks(start, end, width)
        for tick in range(start, end + 1):
            column = vcdtui._cursor_column(tick, start, end, width)
            exact = self.signal.stream.value_at(tick)
            sampled = self.signal.stream.value_at(ticks[column])
            with self.subTest(tick=tick):
                # The sampled tick is at or after the cursor, so the column may
                # be ahead of the readout but must never lag behind it.
                if exact == "0011":
                    self.assertEqual(sampled, "0011")


if __name__ == "__main__":
    unittest.main()
