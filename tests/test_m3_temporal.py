import unittest

import vcdtui


SAMPLE = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 4 $ count [3:0] $end
$var wire 1 % stop $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
b0010 $
0%
$end
#5
1!
#10
0!
b0001 $
#15
1!
#20
0!
b0000 $
1%
"""


class TemporalInspectionTests(unittest.TestCase):
    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(SAMPLE)
        self.signals = vcdtui.select_signals(self.vcd, "clk,count,stop")

    def test_value_before_is_strictly_before_cursor(self):
        count = self.vcd.streams["$"]
        self.assertEqual(count.value_before(20), "0001")
        self.assertEqual(count.value_at(20), "0000")
        self.assertIsNone(count.value_before(0))
        self.assertEqual(count.value_at(0), "0010")

    def test_inspection_marks_changes_at_cursor(self):
        rows = vcdtui.inspect_at(self.signals, 20)
        by_name = {row.signal.reference: row for row in rows}
        self.assertEqual((by_name["count"].before, by_name["count"].after), ("0001", "0000"))
        self.assertTrue(by_name["count"].changed)
        self.assertEqual((by_name["stop"].before, by_name["stop"].after), ("0", "1"))
        self.assertTrue(by_name["stop"].changed)

    def test_inspection_between_events_keeps_same_value(self):
        rows = vcdtui.inspect_at(self.signals, 12)
        by_name = {row.signal.reference: row for row in rows}
        self.assertEqual((by_name["count"].before, by_name["count"].after), ("0001", "0001"))
        self.assertFalse(by_name["count"].changed)

    def test_sampling_is_deterministic(self):
        clk = next(signal for signal in self.signals if signal.reference == "clk")
        self.assertEqual(vcdtui.sample_waveform(clk, 0, 20, 5, ascii_only=True), "_-_-_")
        self.assertEqual(vcdtui.sample_waveform(clk, 0, 20, 5, ascii_only=False), "_‾_‾_")

    def test_cursor_column_is_bounded(self):
        self.assertEqual(vcdtui._cursor_column(0, 0, 20, 11), 0)
        self.assertEqual(vcdtui._cursor_column(10, 0, 20, 11), 5)
        self.assertEqual(vcdtui._cursor_column(20, 0, 20, 11), 10)


if __name__ == "__main__":
    unittest.main()
