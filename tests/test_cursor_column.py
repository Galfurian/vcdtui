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
    def test_the_column_never_starts_after_the_cursor(self):
        for start, end, width in VIEWPORTS:
            edges = vcdtui._column_edges(start, end, width)
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertLessEqual(edges[column], tick)

    def test_the_cursor_is_before_the_next_distinct_edge(self):
        # Together with the previous test this pins the cursor to the column run
        # its tick is drawn across: never behind it, never past it.
        for start, end, width in VIEWPORTS:
            edges = vcdtui._column_edges(start, end, width)
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                following = next(
                    (edge for edge in edges[column + 1 :] if edge > edges[column]),
                    end + 1,
                )
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertTrue(tick < following or column == width - 1)

    def test_a_tick_occupies_the_whole_run_of_columns_it_is_drawn_across(self):
        # Zoomed in past one tick per column, a tick spans several columns; the
        # cursor belongs at the left edge of that run, not its last column.
        self.assertEqual(vcdtui._cursor_column(0, 0, 5, 30), 0)
        self.assertEqual(vcdtui._cursor_column(1, 0, 5, 30), 6)

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
