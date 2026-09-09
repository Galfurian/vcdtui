"""Vectors expand into their individual bits, as gtkwave's tree does.

A bit is a derived signal: its stream records a change only where that bit
actually moved, so edges and transitions on it mean what they say.
"""

import collections
import unittest

import vcdtui

from tests.test_interval_rendering import clock_trace, signal_named
from tests.test_tui_draw_smoke import RecordingScreen

SAMPLE = """\
$timescale 1 ns $end
$scope module tb $end
$var reg 1 ! clk $end
$var reg 4 " count [3:0] $end
$var reg 4 # plain $end
$var real 1 $ level $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0110 "
b0110 #
r1.5 $
$end
#10
b1001 "
#20
b0111 "
#30
r2.0 $
"""


class BitModelTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.count = next(s for s in self.vcd.signals if s.reference == "count")

    def test_bit_numbers_follow_the_declared_range(self):
        self.assertEqual(vcdtui.bit_numbers(self.count), [3, 2, 1, 0])

    def test_bit_numbers_fall_back_to_the_width(self):
        plain = next(s for s in self.vcd.signals if s.reference == "plain")
        self.assertEqual(vcdtui.bit_numbers(plain), [3, 2, 1, 0])

    def test_bit_numbers_support_descending_declarations(self):
        signal = vcdtui.Signal("d", "d", 4, "reg", self.count.stream, "[0:3]")
        self.assertEqual(vcdtui.bit_numbers(signal), [0, 1, 2, 3])

    def test_only_bit_vectors_are_expandable(self):
        clk = next(s for s in self.vcd.signals if s.reference == "clk")
        level = next(s for s in self.vcd.signals if s.reference == "level")
        self.assertFalse(vcdtui.is_expandable_vector(clk))
        self.assertFalse(vcdtui.is_expandable_vector(level))
        self.assertTrue(vcdtui.is_expandable_vector(self.count))

    def test_a_bit_signal_only_changes_where_the_bit_moves(self):
        # count: 0110 -> 1001 -> 0111. Bit 3 (msb): 0->1->0. Bit 1: 1->0->1.
        bit3 = vcdtui.build_bit_signal(self.count, 0)
        self.assertEqual(
            [(c.time, c.value) for c in bit3.stream.changes],
            [(0, "0"), (10, "1"), (20, "0")],
        )
        bit1 = vcdtui.build_bit_signal(self.count, 2)
        self.assertEqual(
            [(c.time, c.value) for c in bit1.stream.changes],
            [(0, "1"), (10, "0"), (20, "1")],
        )

    def test_a_steady_bit_records_only_its_opening_value(self):
        # count bit 2: 1 -> 0 -> 1, and bit 0: 0 -> 1 -> 1
        bit2 = vcdtui.build_bit_signal(self.count, 1)
        self.assertEqual(
            [(c.time, c.value) for c in bit2.stream.changes],
            [(0, "1"), (10, "0"), (20, "1")],
        )
        bit0 = vcdtui.build_bit_signal(self.count, 3)
        self.assertEqual(
            [(c.time, c.value) for c in bit0.stream.changes],
            [(0, "0"), (10, "1")],
        )

    def test_bit_names_carry_the_declared_number(self):
        bit3 = vcdtui.build_bit_signal(self.count, 0)
        self.assertEqual(bit3.reference, "count[3]")
        self.assertEqual(bit3.full_name, "tb.count[3]")
        self.assertEqual(bit3.width, 1)

    def test_edges_on_a_bit_are_the_bits_own(self):
        bit3 = vcdtui.build_bit_signal(self.count, 0)
        self.assertEqual(vcdtui.edge_times(bit3.stream, "rising"), [10])
        self.assertEqual(vcdtui.edge_times(bit3.stream, "falling"), [20])


class BitTreeTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.signals = self.vcd.signals
        self.count_index = next(
            i for i, s in enumerate(self.signals) if s.reference == "count"
        )

    def test_an_expanded_vector_lists_its_bits_msb_first(self):
        items = vcdtui.build_tree_items(
            self.signals, {("tb",)}, {self.count_index}
        )
        bits = [item for item in items if item.kind == "bit"]
        self.assertEqual(
            [item.label for item in bits], ["count[3]", "count[2]", "count[1]", "count[0]"]
        )
        self.assertTrue(all(item.signal_index == self.count_index for item in bits))
        self.assertEqual([item.bit_position for item in bits], [0, 1, 2, 3])

    def test_bits_come_after_their_vector(self):
        items = vcdtui.build_tree_items(
            self.signals, {("tb",)}, {self.count_index}
        )
        labels = [item.label for item in items]
        self.assertLess(labels.index("count[3:0]"), labels.index("count[3]"))

    def test_only_expandable_signals_are_marked(self):
        items = vcdtui.build_tree_items(self.signals, {("tb",)})
        by_label = {item.label: item for item in items if item.kind == "signal"}
        self.assertTrue(by_label["count[3:0]"].expandable)
        self.assertFalse(by_label["clk"].expandable)
        self.assertFalse(by_label["level"].expandable)

    def test_tree_text_marks_expandable_vectors_and_checks_bits(self):
        state = vcdtui.TUIState(
            cursor=0,
            view_start=0,
            view_end=30,
            selected=[True] * len(self.signals),
            expanded_scopes={("tb",)},
            expanded_signals={self.count_index},
            shown_bits={(self.count_index, 0)},
        )
        items = vcdtui.build_tree_items(
            self.signals, state.expanded_scopes, state.expanded_signals
        )
        texts = {
            item.label: vcdtui._tree_item_text(item, state, ascii_only=False)
            for item in items
        }
        self.assertIn("▾", texts["count[3:0]"])
        self.assertEqual(texts["count[3]"], "    [x] count[3]")
        self.assertEqual(texts["count[2]"], "    [ ] count[2]")

    def test_the_arrow_opens_when_the_vector_is_expanded(self):
        state = vcdtui.TUIState(
            cursor=0,
            view_start=0,
            view_end=30,
            selected=[True] * len(self.signals),
            expanded_scopes={("tb",)},
        )
        vector = next(
            item
            for item in vcdtui.build_tree_items(self.signals, state.expanded_scopes)
            if item.label == "count[3:0]"
        )
        self.assertIn(
            "▸", vcdtui._tree_item_text(vector, state, ascii_only=False)
        )
        state.expanded_signals.add(self.count_index)
        vector = next(
            item
            for item in vcdtui.build_tree_items(
                self.signals, state.expanded_scopes, state.expanded_signals
            )
            if item.label == "count[3:0]"
        )
        self.assertIn(
            "▾", vcdtui._tree_item_text(vector, state, ascii_only=False)
        )


class WaveRowTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.signals = self.vcd.signals
        self.count_index = next(
            i for i, s in enumerate(self.signals) if s.reference == "count"
        )

    def state(self, **overrides):
        values = dict(
            cursor=0,
            view_start=0,
            view_end=30,
            selected=[True] * len(self.signals),
            display_formats=["binary"] * len(self.signals),
        )
        values.update(overrides)
        return vcdtui.TUIState(**values)

    def rows(self, state):
        return [row.signal.reference for row in vcdtui.visible_wave_rows(self.signals, state)]

    def test_bits_are_drawn_under_their_vector(self):
        state = self.state(shown_bits={(self.count_index, 3), (self.count_index, 0)})
        self.assertEqual(
            self.rows(state),
            ["clk", "count", "count[3]", "count[0]", "plain", "level"],
        )

    def test_a_bit_survives_its_parent_being_hidden(self):
        selected = [True] * len(self.signals)
        selected[self.count_index] = False
        state = self.state(selected=selected, shown_bits={(self.count_index, 0)})
        self.assertEqual(
            self.rows(state),
            ["clk", "plain", "level", "count[3]"],
        )

    def test_bit_signals_are_built_once_and_cached(self):
        state = self.state(shown_bits={(self.count_index, 0)})
        first = vcdtui.visible_wave_rows(self.signals, state)
        second = vcdtui.visible_wave_rows(self.signals, state)
        self.assertIs(first[-1].signal, second[-1].signal)
        self.assertEqual(len(state.bit_signals), 1)

    def test_bit_rows_display_binary(self):
        state = self.state(display_formats=["binary"] * len(self.signals))
        rows = vcdtui.visible_wave_rows(self.signals, state)
        self.assertEqual(
            vcdtui.wave_row_format(rows[1], state),
            state.display_formats[1],
        )


class BitFrameTests(unittest.TestCase):
    def test_a_frame_with_expanded_bits_draws_their_tracks(self):
        vcd = clock_trace(5, 2000)
        vector_index = next(
            i for i, s in enumerate(vcd.signals) if s.reference == "v"
        )
        state = vcdtui.TUIState(
            cursor=0,
            view_start=0,
            view_end=2000,
            selected=[True] * len(vcd.signals),
            expanded_scopes={("tb",)},
            expanded_signals={vector_index},
            shown_bits={(vector_index, 0), (vector_index, 3)},
            display_formats=["binary"] * len(vcd.signals),
        )
        screen = RecordingScreen(40, 120)
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
        frame = screen.text()
        self.assertIn("v[3]", frame)
        self.assertIn("v[0]", frame)

    def test_a_bit_track_uses_the_scalar_renderer(self):
        vcd = clock_trace(5, 2000)
        vector = signal_named(vcd, "v")
        bit = vcdtui.build_bit_signal(vector, 0)
        rows = vcdtui.render_waveform_track_rows(
            bit, 0, 120, 60, ascii_only=False, height=1
        )
        self.assertEqual(
            rows[0],
            vcdtui.render_scalar_track(bit, 0, 120, 60, ascii_only=False),
        )


if __name__ == "__main__":
    unittest.main()
