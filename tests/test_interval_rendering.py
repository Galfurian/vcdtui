"""A column is an interval of ticks, not a single sampled tick.

Point sampling aliases: a clock toggling faster than one column per period was
drawn as a flat line, which is not an imprecise picture but a false one. A
column now summarises everything that happens inside it, and says so when there
is more than one change to show.
"""

import unittest

import vcdtui


def clock_trace(half_period, last, *, pulse=None):
    """A 1-bit clock, optionally with a single narrow pulse on a second signal.

    Changes are emitted in timestamp order, which the VCD grammar requires.
    """
    at = {0: ["0!", 'b0 "', "0#"]}
    for tick in range(half_period, last + 1, half_period):
        phase = tick // half_period
        at.setdefault(tick, []).extend(
            ["1!" if phase % 2 else "0!", "b%s " % format(phase % 16, "04b") + '"']
        )
    if pulse is not None:
        rise, fall = pulse
        at.setdefault(rise, []).append("1#")
        at.setdefault(fall, []).append("0#")
    lines = [
        "$timescale 1 ns $end",
        "$scope module tb $end",
        "$var reg 1 ! clk $end",
        '$var reg 4 " v [3:0] $end',
        "$var reg 1 # pulse $end",
        "$upscope $end",
        "$enddefinitions $end",
    ]
    for tick in sorted(at):
        lines.append(f"#{tick}")
        lines.extend(at[tick])
    return vcdtui.parse_vcd_text("\n".join(lines) + "\n")


def signal_named(vcd, reference):
    return next(signal for signal in vcd.signals if signal.reference == reference)


class ColumnEdgeTests(unittest.TestCase):
    def test_a_column_is_a_half_open_interval(self):
        self.assertEqual(vcdtui._column_edges(0, 40, 4), [0, 10, 20, 30, 40])

    def test_there_is_one_more_edge_than_columns(self):
        for width in (1, 2, 17, 60):
            self.assertEqual(len(vcdtui._column_edges(0, 100, width)), width + 1)

    def test_the_edges_cover_the_whole_viewport(self):
        edges = vcdtui._column_edges(7, 53, 13)
        self.assertEqual(edges[0], 7)
        self.assertEqual(edges[-1], 53)
        self.assertEqual(edges, sorted(edges))

    def test_a_degenerate_viewport_does_not_raise(self):
        self.assertEqual(vcdtui._column_edges(5, 5, 3), [5, 5, 5, 5])
        self.assertEqual(vcdtui._column_edges(0, 10, 0), [])


class CursorAgreesWithColumnsTests(unittest.TestCase):
    def test_the_cursor_column_is_the_one_whose_interval_holds_the_tick(self):
        for start, end, width in [(0, 40, 30), (0, 1180, 60), (0, 5, 30), (10, 30, 21)]:
            edges = vcdtui._column_edges(start, end, width)
            for tick in range(start, end + 1):
                column = vcdtui._cursor_column(tick, start, end, width)
                following = next(
                    (edge for edge in edges[column + 1 :] if edge > edges[column]),
                    end + 1,
                )
                with self.subTest(view=(start, end, width), tick=tick):
                    self.assertLessEqual(edges[column], tick)
                    # The last column owns the final tick, so it closes
                    # inclusively; zoomed in, repeated edges mean the next
                    # boundary is the next distinct one.
                    self.assertTrue(tick < following or column == width - 1)


class DenseColumnTests(unittest.TestCase):
    def test_a_clock_faster_than_one_column_is_marked_not_flattened(self):
        clk = signal_named(clock_trace(5, 1200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 1180, 60, ascii_only=False)
        self.assertEqual(track, "▓" * 60)

    def test_the_ascii_form_uses_a_hash(self):
        clk = signal_named(clock_trace(5, 1200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 1180, 60, ascii_only=True)
        self.assertEqual(track, "#" * 60)

    def test_a_pulse_narrower_than_a_column_is_still_visible(self):
        # Point sampling stepped straight over this pulse and drew nothing.
        vcd = clock_trace(5, 1200, pulse=(105, 106))
        pulse = signal_named(vcd, "pulse")
        track = vcdtui.render_scalar_track(pulse, 0, 1180, 60, ascii_only=False)
        column = vcdtui._cursor_column(105, 0, 1180, 60)
        self.assertEqual(track[column], "▓")
        self.assertEqual(track.count("▓"), 1)

    def test_a_dense_bus_column_is_marked_too(self):
        v = signal_named(clock_trace(5, 1200), "v")
        track = vcdtui.render_bus_track(v, 0, 1180, 60, ascii_only=False)
        self.assertEqual(track, "▓" * 60)

    def test_the_number_of_changes_in_a_column_is_reportable(self):
        clk = signal_named(clock_trace(5, 1200), "clk")
        counts = [
            vcdtui.changes_in_column(clk, 0, 1180, 60, column) for column in range(60)
        ]
        self.assertTrue(all(count >= 2 for count in counts))
        self.assertEqual(sum(counts), len(clk.stream.changes_between(0, 1180)) - 1)


class ChangeRangeTests(unittest.TestCase):
    """The counting shortcut has to agree with the obvious definition.

    Counting by index rather than slicing the changes out took a track on a
    400k-change trace from 15 ms to 0.4 ms, which is the difference between a
    sluggish and an instant frame; the risk it carries is an off-by-one.
    """

    def setUp(self):
        self.stream = signal_named(clock_trace(5, 400), "clk").stream

    def naive(self, low, high, view_start):
        inside = [
            change
            for change in self.stream.changes
            if low <= change.time < high
        ]
        if (
            inside
            and inside[0].time == view_start
            and self.stream.value_before(view_start) is None
        ):
            inside = inside[1:]
        return len(inside)

    def test_the_index_range_counts_what_the_obvious_filter_counts(self):
        for view_start in (0, 5, 7, 100):
            for low in range(view_start, view_start + 40):
                for high in range(low, low + 40):
                    first, last = vcdtui._change_range(
                        self.stream, low, high, view_start
                    )
                    with self.subTest(view_start=view_start, low=low, high=high):
                        self.assertEqual(last - first, self.naive(low, high, view_start))

    def test_the_first_index_points_at_the_first_counted_change(self):
        first, last = vcdtui._change_range(self.stream, 12, 30, 0)
        self.assertEqual(last - first, 3)  # 15, 20 and 25
        self.assertEqual(self.stream.changes[first].time, 15)


class FaithfulWhenResolvableTests(unittest.TestCase):
    def test_a_regular_clock_renders_with_a_regular_period(self):
        # 2 ticks per column and a 10-tick period, so one period is exactly five
        # columns. Point sampling drew the duty cycle changing halfway across.
        clk = signal_named(clock_trace(5, 200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 120, 60, ascii_only=False)
        period = track[2:7]
        self.assertEqual(period, "/‾‾\\_")
        for offset in range(2, 57, 5):
            with self.subTest(offset=offset):
                self.assertEqual(track[offset : offset + 5], period)

    def test_edges_are_counted_not_guessed(self):
        clk = signal_named(clock_trace(5, 200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 120, 60, ascii_only=False)
        rising = len([t for t in vcdtui.edge_times(clk.stream, "rising") if 0 < t <= 120])
        falling = len([t for t in vcdtui.edge_times(clk.stream, "falling") if 0 < t <= 120])
        self.assertEqual(track.count("/"), rising)
        self.assertEqual(track.count("\\"), falling)

    def test_an_empty_column_keeps_the_level_it_inherits(self):
        # Zoomed in past one tick per column some columns cover no ticks at all.
        # Drawn from the value AT their edge, one sitting on a change tick showed
        # the new level before the column that draws the edge, giving "‾‾_\" and
        # "__‾/". An empty column belongs to the run it sits in.
        clk = signal_named(clock_trace(5, 200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 60, 77, ascii_only=False)
        for artefact in ("‾_\\", "_‾/", "‾_/", "_‾\\"):
            with self.subTest(artefact=artefact):
                self.assertNotIn(artefact, track)

    def test_a_level_run_is_never_broken_by_the_opposite_level(self):
        clk = signal_named(clock_trace(5, 200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 60, 77, ascii_only=False)
        # Between two edges the level must be constant.
        segments = track.replace("/", " ").replace("\\", " ").split()
        for segment in segments:
            with self.subTest(segment=segment):
                self.assertIn(set(segment), [{"_"}, {"‾"}])

    def test_an_edge_needs_a_value_to_come_from(self):
        # The first recorded value is not a transition: there is no before.
        clk = signal_named(clock_trace(5, 200), "clk")
        track = vcdtui.render_scalar_track(clk, 0, 120, 60, ascii_only=False)
        self.assertEqual(track[0], "_")

    def test_a_bus_boundary_lands_on_the_column_holding_the_change(self):
        v = signal_named(clock_trace(20, 200), "v")
        track = vcdtui.render_bus_track(v, 0, 200, 60, ascii_only=False)
        for tick in (20, 40, 60):
            column = vcdtui._cursor_column(tick, 0, 200, 60)
            with self.subTest(tick=tick):
                self.assertEqual(track[column], "│")

    def test_a_label_that_does_not_fit_is_omitted_not_truncated(self):
        # "0000" cut down to "0" reads as the value being 0, which is the same
        # kind of confident wrong answer as drawing a busy clock flat.
        v = signal_named(clock_trace(5, 200), "v")
        track = vcdtui.render_bus_track(v, 0, 120, 60, ascii_only=False)
        for run in track.replace("│", " ").replace("▓", " ").split():
            with self.subTest(run=run):
                self.assertIn(run.strip("─"), ("", "0000", "0001", "0010", "0011",
                                               "0100", "0101", "0110", "0111",
                                               "1000", "1001", "1010", "1011"))

    def test_bus_labels_still_fill_the_held_runs(self):
        v = signal_named(clock_trace(20, 200), "v")
        track = vcdtui.render_bus_track(v, 0, 200, 60, ascii_only=False)
        self.assertIn("0001", track)
        self.assertIn("0010", track)

    def test_every_track_keeps_the_requested_width(self):
        vcd = clock_trace(5, 200)
        for signal in vcd.signals:
            for width in (1, 7, 37, 60):
                with self.subTest(signal=signal.reference, width=width):
                    self.assertEqual(
                        len(
                            vcdtui.render_waveform_track(
                                signal, 0, 120, width, ascii_only=False
                            )
                        ),
                        width,
                    )


class DensityNoteTests(unittest.TestCase):
    """The count is what makes the glyph mean "zoom in" rather than "?"."""

    def setUp(self):
        self.clk = signal_named(clock_trace(5, 1300), "clk")

    def note(self, cursor, start, end, width, ascii_only=False):
        return vcdtui.column_density_note(
            self.clk, cursor, start, end, width, ascii_only=ascii_only
        )

    def test_a_dense_column_reports_how_much_it_hides(self):
        self.assertEqual(self.note(600, 0, 1180, 60), "▓ 4 changes in this column")

    def test_the_ascii_form_matches_the_ascii_glyph(self):
        self.assertEqual(
            self.note(600, 0, 1180, 60, ascii_only=True), "# 4 changes in this column"
        )

    def test_a_resolvable_column_says_nothing(self):
        self.assertEqual(self.note(30, 0, 60, 60), "")

    def test_a_degenerate_width_says_nothing(self):
        self.assertEqual(self.note(600, 0, 1180, 0), "")


class UnknownAndUndefinedTests(unittest.TestCase):
    TEXT = """\
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

    def setUp(self):
        self.signal = vcdtui.parse_vcd_text(self.TEXT).signals[0]

    def test_a_transition_into_x_shows_x(self):
        track = vcdtui.render_scalar_track(self.signal, 0, 30, 30, ascii_only=False)
        self.assertEqual(track[vcdtui._cursor_column(10, 0, 30, 30)], "x")

    def test_a_transition_into_z_shows_z(self):
        track = vcdtui.render_scalar_track(self.signal, 0, 30, 30, ascii_only=False)
        self.assertEqual(track[vcdtui._cursor_column(20, 0, 30, 30)], "z")


if __name__ == "__main__":
    unittest.main()
