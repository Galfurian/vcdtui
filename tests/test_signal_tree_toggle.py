import collections
import unittest

import vcdtui

from tests.test_interval_rendering import clock_trace
from tests.test_tui_draw_smoke import RecordingScreen


def draw_with_signal_tree(show_signal_tree: bool) -> str:
    vcd = clock_trace(5, 2000)
    signals = vcd.signals
    state = vcdtui.TUIState(
        cursor=0,
        view_start=0,
        view_end=2000,
        selected=[True] * len(signals),
        expanded_scopes={("tb",)},
        display_formats=["binary"] * len(signals),
        show_signal_tree=show_signal_tree,
    )
    screen = RecordingScreen(height=30, width=120)
    vcdtui._draw_tui(
        screen,
        vcd,
        signals,
        0,
        vcd.last_time,
        state,
        ascii_only=False,
        attrs=collections.defaultdict(int),
    )
    return screen.text()


class SignalTreeToggleTests(unittest.TestCase):
    def test_hidden_tree_reclaims_the_left_column(self):
        visible_header = draw_with_signal_tree(True).splitlines()[3]
        hidden_header = draw_with_signal_tree(False).splitlines()[3]

        self.assertTrue(visible_header.startswith("signals"))
        self.assertTrue(hidden_header.startswith("shown @cursor"))
        self.assertLess(hidden_header.index("waveform"), visible_header.index("waveform"))

    def test_hiding_tree_moves_focus_to_waveform(self):
        state = vcdtui.TUIState(
            cursor=0,
            view_start=0,
            view_end=1,
            selected=[True],
            focus_pane="tree",
        )

        vcdtui._toggle_signal_tree(state)
        self.assertFalse(state.show_signal_tree)
        self.assertEqual(state.focus_pane, "wave")
        self.assertEqual(state.status, "signal-selection pane hidden")

        vcdtui._toggle_signal_tree(state)
        self.assertTrue(state.show_signal_tree)
        self.assertEqual(state.focus_pane, "wave")
        self.assertEqual(state.status, "signal-selection pane shown")

    def test_help_documents_the_toggle(self):
        help_text = "\n".join(vcdtui._help_lines(ascii_only=False))
        self.assertIn("s                   show/hide the signal-selection pane", help_text)


if __name__ == "__main__":
    unittest.main()
