"""A tick spanning several columns owns the first of them, not the last.

Zoomed in past one tick per column, one tick is drawn across a run of columns.
The cursor sat at the left edge of that run while the change was drawn at its
right edge, so a bus boundary appeared two or three characters after the cursor
that already reported the new value.
"""

import unittest
from pathlib import Path

import vcdtui


REAL_VALUES = Path("examples/qualification/real_values.vcd")


class ReportedCaseTests(unittest.TestCase):
    """`vcdtui examples/qualification/real_values.vcd`, cursor on 10ns."""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd(REAL_VALUES)
        self.state = next(s for s in self.vcd.signals if s.reference == "state")

    def test_the_cursor_sits_on_the_boundary_it_reports(self):
        for width in (60, 62, 64, 77, 100):
            track = vcdtui.render_bus_track(self.state, 0, 20, width, ascii_only=False)
            cursor = vcdtui._cursor_column(10, 0, 20, width)
            with self.subTest(width=width):
                self.assertEqual(track.index("│"), cursor)

    def test_the_new_value_fills_the_rest_of_its_tick(self):
        # Ticks 10 upwards are BUSY, so every column of tick 10's run is BUSY.
        width = 60
        track = vcdtui.render_bus_track(self.state, 0, 20, width, ascii_only=False)
        edges = vcdtui._column_edges(0, 20, width)
        run = [column for column in range(width) if edges[column] == 10]
        self.assertGreater(len(run), 1)
        self.assertEqual(track[run[0]], "│")
        self.assertNotIn("│", track[run[0] + 1 :])


class DrawnFrameTests(unittest.TestCase):
    """End to end: the ruler cursor mark and the boundary in the same column."""

    def test_the_ruler_cursor_and_the_bus_boundary_line_up(self):
        import collections

        from tests.test_tui_draw_smoke import RecordingScreen

        vcd = vcdtui.parse_vcd(REAL_VALUES)
        state = vcdtui.TUIState(
            cursor=10,
            view_start=0,
            view_end=20,
            selected=[True] * len(vcd.signals),
            expanded_scopes={("top",)},
            display_formats=["binary"] * len(vcd.signals),
        )
        screen = RecordingScreen(14, 108)
        vcdtui._draw_tui(
            screen,
            vcd,
            vcd.signals,
            0,
            vcd.last_time,
            state,
            ascii_only=False,
            attrs=collections.defaultdict(int),
        )
        rows = screen.text().splitlines()
        ruler = next(row for row in rows if "^" in row)
        drift = next(row for row in rows if "-3.5e-9" in row)
        self.assertEqual(ruler.index("^"), drift.index("│", ruler.index("^") - 1))


class RunOwnershipTests(unittest.TestCase):
    VIEWPORTS = [(0, 20, 60), (0, 5, 30), (0, 20, 77), (10, 30, 21), (0, 40, 30)]

    def test_a_tick_is_owned_by_exactly_one_column(self):
        for start, end, width in self.VIEWPORTS:
            edges = tuple(vcdtui._column_edges(start, end, width))
            owners = {}
            for column in range(width):
                low, high = vcdtui._column_span(edges, column, end)
                for tick in range(low, high):
                    with self.subTest(view=(start, end, width), tick=tick):
                        self.assertNotIn(tick, owners)
                    owners[tick] = column
            with self.subTest(view=(start, end, width)):
                self.assertEqual(sorted(owners), list(range(start, end + 1)))

    def test_the_owner_of_a_tick_is_where_its_cursor_is_drawn(self):
        for start, end, width in self.VIEWPORTS:
            edges = tuple(vcdtui._column_edges(start, end, width))
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                low, high = vcdtui._column_span(edges, column, end)
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertTrue(low <= tick < high)


class EmptyColumnsFollowTheirOwnerTests(unittest.TestCase):
    def test_the_level_after_an_edge_fills_the_rest_of_the_tick(self):
        # The run owner draws the edge, so the columns after it are already on
        # the new level; no "/‾‾_\" with the old level leaking back in.
        text = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 1 ! clk $end
$upscope $end
$enddefinitions $end
#0
0!
#5
1!
#10
0!
"""
        clk = vcdtui.parse_vcd_text(text).signals[0]
        track = vcdtui.render_scalar_track(clk, 0, 10, 33, ascii_only=False)
        rise = vcdtui._cursor_column(5, 0, 10, 33)
        fall = vcdtui._cursor_column(10, 0, 10, 33)
        self.assertEqual(track[rise], "/")
        self.assertEqual(track[fall], "\\")
        # Between them the level is high, all the way to the falling edge.
        self.assertEqual(set(track[rise + 1 : fall]), {"‾"})
        self.assertEqual(set(track[:rise]), {"_"})


class FinalTickTests(unittest.TestCase):
    """The viewport's last tick owns a block of columns like every other tick.

    A linear cut gave the final tick no column at all: the previous run's owner
    drew its change and the columns after it contradicted it (a rising edge
    followed by the old low level, `/___` at one row and `┌ │ │ ┘` floating in
    a taller one), and the cursor could not move onto the tick, so pressing
    right at the last-but-one tick left the cursor mark standing still while
    the exact readout moved.
    """

    TEXT = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 1 ! s $end
$upscope $end
$enddefinitions $end
#0
0!
#4
1!
#5
0!
"""

    def setUp(self):
        self.signal = vcdtui.parse_vcd_text(self.TEXT).signals[0]

    def test_the_final_tick_has_a_column_of_its_own_when_zoomed_in(self):
        for start, end, width in [(0, 5, 20), (0, 5, 30), (0, 10, 33), (10, 30, 21), (0, 20, 60)]:
            if end - start >= width:
                continue
            with self.subTest(view=(start, end, width)):
                self.assertNotEqual(
                    vcdtui._cursor_column(end, start, end, width),
                    vcdtui._cursor_column(end - 1, start, end, width),
                )

    def test_no_edge_is_contradicted_by_the_level_after_it(self):
        # Rise at 4 and fall at 5, the viewport's final tick: the pulse must be
        # drawn whole, not as an edge with the old level leaking back in.
        states = vcdtui._scalar_column_states(self.signal, 0, 5, 20)
        for index, state in enumerate(states):
            previous = states[index - 1] if index else None
            following = states[index + 1] if index + 1 < len(states) else None
            with self.subTest(column=index, state=state):
                if state == "rising":
                    self.assertNotIn(previous, ("high",))
                    self.assertNotIn(following, ("low",))
                if state == "falling":
                    self.assertNotIn(previous, ("low",))
                    self.assertNotIn(following, ("high",))

    def test_a_pulse_on_the_final_tick_draws_whole_at_height_four(self):
        rows = vcdtui.render_scalar_track_rows(
            self.signal, 0, 5, 20, ascii_only=False, height=4
        )
        rise = vcdtui._cursor_column(4, 0, 5, 20)
        fall = vcdtui._cursor_column(5, 0, 5, 20)
        self.assertEqual(rows[0][rise : fall + 1], "┌──┐")
        self.assertEqual(rows[3][rise : fall + 1], "┘  └")
        self.assertEqual(set(rows[3][fall + 1 :]), {"─"})
        self.assertEqual(set(rows[0][:rise]), {" "})

    def test_a_change_on_the_final_tick_is_drawn_at_its_own_column(self):
        states = vcdtui._scalar_column_states(self.signal, 0, 5, 20)
        self.assertEqual(states[vcdtui._cursor_column(4, 0, 5, 20)], "rising")
        self.assertEqual(states[vcdtui._cursor_column(5, 0, 5, 20)], "falling")


if __name__ == "__main__":
    unittest.main()
