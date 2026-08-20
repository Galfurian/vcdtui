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
    def test_the_cursor_is_drawn_in_the_column_that_owns_its_tick(self):
        # The ownership invariant itself lives in test_tick_run_alignment; this
        # checks it holds across the viewports that exercised the old bug.
        for start, end, width in VIEWPORTS:
            edges = tuple(vcdtui._column_edges(start, end, width))
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                low, high = vcdtui._column_span(edges, column, end)
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertTrue(low <= tick < high)

    def test_a_tick_occupies_the_whole_run_of_columns_it_is_drawn_across(self):
        # Zoomed in past one tick per column, a tick spans several columns and
        # the cursor sits at the left edge of that run, where its value starts.
        self.assertEqual(vcdtui._cursor_column(0, 0, 5, 30), 0)
        self.assertEqual(vcdtui._cursor_column(1, 0, 5, 30), 6)

    def test_the_viewport_start_maps_to_the_first_column(self):
        for start, end, width in VIEWPORTS:
            with self.subTest(view=(start, end, width)):
                self.assertEqual(vcdtui._cursor_column(start, start, end, width), 0)

    def test_the_viewport_end_maps_to_the_last_column_that_owns_a_tick(self):
        # With at least one column per tick that is the last column. Zoomed in
        # further, the final tick shares a run and the cursor sits at its start.
        for start, end, width in VIEWPORTS:
            column = vcdtui._cursor_column(end, start, end, width)
            edges = tuple(vcdtui._column_edges(start, end, width))
            owners = [
                candidate
                for candidate in range(width)
                if vcdtui._column_span(edges, candidate, end)[1]
                > vcdtui._column_span(edges, candidate, end)[0]
            ]
            with self.subTest(view=(start, end, width)):
                self.assertEqual(column, owners[-1])
                if end - start >= width:
                    self.assertEqual(column, width - 1)

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
        edges = vcdtui._column_edges(start, end, width)
        for tick in range(start, end + 1):
            column = vcdtui._cursor_column(tick, start, end, width)
            with self.subTest(tick=tick):
                # The column the cursor sits in starts at or before its tick, so
                # the value the column was drawn from is never from after it.
                self.assertLessEqual(edges[column], tick)
                if self.signal.stream.value_at(tick) == "0000":
                    self.assertEqual(self.signal.stream.value_at(edges[column]), "0000")


if __name__ == "__main__":
    unittest.main()
