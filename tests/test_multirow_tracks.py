"""Tracks taller than one row.

One-row tracks are the committed contract; two or more rows give the wave a
real shape. The multi-row renderers classify columns exactly like the one-row
one, so a taller track shows the same transitions in the same columns.
"""

import collections
import unittest

import vcdtui

from tests.test_interval_rendering import clock_trace, signal_named
from tests.test_tui_draw_smoke import RecordingScreen


class TrackHeightTests(unittest.TestCase):
    def test_default_track_height_is_two_rows(self):
        state = vcdtui.TUIState(0, 0, 1, [])
        self.assertEqual(state.track_height, 2)

    def test_height_is_clamped_to_the_supported_range(self):
        self.assertEqual(vcdtui.adjust_track_height(1, -1), 1)
        self.assertEqual(vcdtui.adjust_track_height(4, 1), 4)
        self.assertEqual(vcdtui.adjust_track_height(2, 1), 3)
        self.assertEqual(vcdtui.adjust_track_height(3, -2), 1)


class ScalarMultiRowTests(unittest.TestCase):
    def setUp(self):
        self.clk = signal_named(clock_trace(5, 200), "clk")

    def rows(self, *, height, ascii_only=False):
        return vcdtui.render_scalar_track_rows(
            self.clk, 0, 120, 60, ascii_only=ascii_only, height=height
        )

    def test_one_row_matches_the_single_line_track(self):
        for ascii_only in (False, True):
            with self.subTest(ascii_only=ascii_only):
                self.assertEqual(
                    self.rows(height=1, ascii_only=ascii_only),
                    [
                        vcdtui.render_scalar_track(
                            self.clk, 0, 120, 60, ascii_only=ascii_only
                        )
                    ],
                )

    def test_every_row_keeps_the_requested_width(self):
        for height in (1, 2, 3, 4):
            with self.subTest(height=height):
                for row in self.rows(height=height):
                    self.assertEqual(len(row), 60)

    def test_a_three_row_track_draws_a_square_wave(self):
        # The single-line track puts the period "/‾‾\_ " at columns 2..7; the
        # same columns must become the box shape, not a second opinion.
        rows = self.rows(height=3)
        self.assertEqual(rows[0][2:7], "┌──┐ ")
        self.assertEqual(rows[1][2:7], "│  │ ")
        self.assertEqual(rows[2][2:7], "┘  └─")

    def test_a_two_row_ascii_track_draws_the_classic_shape(self):
        rows = self.rows(height=2, ascii_only=True)
        rising = vcdtui.render_scalar_track(
            self.clk, 0, 120, 60, ascii_only=True
        ).index("/")
        self.assertEqual(rows[1][rising], "/")
        self.assertEqual(rows[0][rising], " ")
        # The high level runs on the top row right after the rise.
        self.assertEqual(rows[0][rising + 1], "_")

    def test_a_three_row_ascii_track_uses_vertical_edges(self):
        rows = self.rows(height=3, ascii_only=True)
        single = vcdtui.render_scalar_track(
            self.clk, 0, 120, 60, ascii_only=True
        )
        rising = single.index("/")
        falling = single.index("\\")
        self.assertEqual([row[rising] for row in rows], [" ", "|", "|"])
        self.assertEqual([row[falling] for row in rows], [" ", "|", "|"])

    def test_the_low_level_runs_along_the_bottom_row(self):
        rows = self.rows(height=3)
        single = vcdtui.render_scalar_track(self.clk, 0, 120, 60, ascii_only=False)
        for column, glyph in enumerate(single):
            if glyph == "_":
                with self.subTest(column=column):
                    self.assertEqual(rows[2][column], "─")
                    self.assertEqual(rows[0][column], " ")

    def test_the_high_level_runs_along_the_top_row(self):
        rows = self.rows(height=3)
        single = vcdtui.render_scalar_track(self.clk, 0, 120, 60, ascii_only=False)
        for column, glyph in enumerate(single):
            if glyph == "‾":
                with self.subTest(column=column):
                    self.assertEqual(rows[0][column], "─")
                    self.assertEqual(rows[2][column], " ")

    def test_a_dense_column_fills_every_row(self):
        clk = signal_named(clock_trace(5, 1200), "clk")
        rows = vcdtui.render_scalar_track_rows(
            clk, 0, 1180, 60, ascii_only=False, height=3
        )
        self.assertEqual(rows, ["▓" * 60] * 3)

    def test_x_fills_the_whole_column(self):
        text = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 1 ! s $end
$upscope $end
$enddefinitions $end
#0
0!
#10
x!
#20
z!
"""
        signal = vcdtui.parse_vcd_text(text).signals[0]
        rows = vcdtui.render_scalar_track_rows(
            signal, 0, 30, 30, ascii_only=False, height=3
        )
        x_column = vcdtui._cursor_column(15, 0, 30, 30)
        z_column = vcdtui._cursor_column(25, 0, 30, 30)
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(row[x_column], "x")
                self.assertEqual(row[z_column], "z")


class BusMultiRowTests(unittest.TestCase):
    def setUp(self):
        self.bus = signal_named(clock_trace(20, 200), "v")

    def rows(self, *, height, ascii_only=False):
        return vcdtui.render_bus_track_rows(
            self.bus, 0, 200, 60, ascii_only=ascii_only, height=height
        )

    def test_one_row_matches_the_single_line_track(self):
        self.assertEqual(
            self.rows(height=1),
            [vcdtui.render_bus_track(self.bus, 0, 200, 60, ascii_only=False)],
        )

    def test_every_row_keeps_the_requested_width(self):
        for height in (1, 2, 3, 4):
            with self.subTest(height=height):
                for row in self.rows(height=height):
                    self.assertEqual(len(row), 60)

    def test_two_rows_put_the_labels_on_their_own_row(self):
        rows = self.rows(height=2)
        self.assertEqual(
            rows[1], vcdtui.render_bus_track(
                self.bus, 0, 200, 60, ascii_only=False, show_labels=False
            )
        )
        self.assertIn("0001", rows[0])
        # Away from the labels the row stays blank, so the label is legible.
        self.assertNotIn("─", rows[0])
        self.assertNotIn("│", rows[0])

    def test_two_row_bus_can_suppress_the_label_under_the_cursor(self):
        baseline = self.rows(height=2)
        label_column = baseline[0].index("0001")
        rows = vcdtui.render_bus_track_rows(
            self.bus, 0, 200, 60, ascii_only=False, height=2,
            cursor_column=label_column,
        )
        self.assertNotIn("0001", rows[0])
        self.assertIn("0010", rows[0])

    def test_two_row_bus_does_not_duplicate_labels_inside_waveform(self):
        rows = self.rows(height=2)
        self.assertIn("0001", rows[0])
        self.assertNotIn("0001", rows[1])

    def test_three_rows_draw_a_box_with_the_label_inside(self):
        rows = self.rows(height=3)
        single = vcdtui.render_bus_track(self.bus, 0, 200, 60, ascii_only=False)
        for column, glyph in enumerate(single):
            if glyph != "│":
                continue
            with self.subTest(column=column):
                self.assertEqual(rows[0][column], "┬")
                self.assertEqual(rows[1][column], "│")
                self.assertEqual(rows[2][column], "┴")
        # The label sits centred in the middle row, over a bordered run.
        self.assertIn("0001", rows[1])
        self.assertNotIn("0001", rows[0])

    def test_a_label_that_fits_the_single_line_track_also_fits_the_box(self):
        rows = self.rows(height=3)
        single = vcdtui.render_bus_track(self.bus, 0, 200, 60, ascii_only=False)
        self.assertEqual("0001" in single, "0001" in rows[1])

    def test_an_ascii_box_uses_plus_and_pipe(self):
        rows = self.rows(height=3, ascii_only=True)
        single = vcdtui.render_bus_track(self.bus, 0, 200, 60, ascii_only=True)
        boundary = single.index("|")
        self.assertEqual(rows[0][boundary], "+")
        self.assertEqual(rows[1][boundary], "|")
        self.assertEqual(rows[2][boundary], "+")

    def test_a_dense_bus_column_fills_every_row(self):
        bus = signal_named(clock_trace(5, 1200), "v")
        rows = vcdtui.render_bus_track_rows(
            bus, 0, 1180, 60, ascii_only=False, height=3
        )
        self.assertEqual(rows, ["▓" * 60] * 3)


class WaveformTrackRowsTests(unittest.TestCase):
    def test_scalars_use_the_scalar_renderer_at_any_height(self):
        clk = signal_named(clock_trace(5, 200), "clk")
        self.assertEqual(
            vcdtui.render_waveform_track_rows(
                clk, 0, 120, 60, ascii_only=False, height=3
            ),
            vcdtui.render_scalar_track_rows(
                clk, 0, 120, 60, ascii_only=False, height=3
            ),
        )

    def test_buses_use_the_bus_renderer_at_any_height(self):
        bus = signal_named(clock_trace(20, 200), "v")
        self.assertEqual(
            vcdtui.render_waveform_track_rows(
                bus, 0, 200, 60, ascii_only=False, height=3
            ),
            vcdtui.render_bus_track_rows(
                bus, 0, 200, 60, ascii_only=False, height=3
            ),
        )


def draw(vcd, state, *, height=30, width=120):
    screen = RecordingScreen(height, width)
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
    return screen.text()


class MultiRowFrameTests(unittest.TestCase):
    def setUp(self):
        self.vcd = clock_trace(5, 2000)

    def state(self, **overrides):
        values = dict(
            cursor=0,
            view_start=0,
            view_end=120,
            selected=[True] * len(self.vcd.signals),
            expanded_scopes={("tb",)},
            display_formats=["binary"] * len(self.vcd.signals),
        )
        values.update(overrides)
        return vcdtui.TUIState(**values)

    def test_a_taller_frame_draws_box_glyphs_and_still_renders(self):
        frame = draw(self.vcd, self.state(track_height=3), height=40)
        self.assertIn("┌", frame)
        self.assertIn("└", frame)

    def test_a_taller_frame_shows_fewer_signals_per_screen(self):
        # The tree lists every signal regardless; only the wave pane is bounded,
        # so hide it and count what the tracks themselves can show.
        flat = draw(self.vcd, self.state(track_height=1, show_signal_tree=False), height=14)
        tall = draw(self.vcd, self.state(track_height=3, show_signal_tree=False), height=14)
        # "pulse" is the third signal: visible when flat, pushed out when each
        # track costs four rows (three plus a separator).
        self.assertIn("pulse", flat)
        self.assertNotIn("pulse", tall)

    def test_the_frame_returns_to_one_row(self):
        frame = draw(self.vcd, self.state(track_height=1), height=40)
        self.assertNotIn("┌", frame)

    def test_two_row_bus_cursor_value_aligns_with_waveform_row(self):
        frame = draw(self.vcd, self.state(track_height=2), height=40)
        rows = frame.splitlines()
        bus_row = next(i for i, row in enumerate(rows) if "v[3:0]" in row and "0000" in row)
        self.assertIn("0000", rows[bus_row])
        self.assertNotIn("0000", rows[bus_row - 1])


if __name__ == "__main__":
    unittest.main()
