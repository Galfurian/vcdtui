"""Real and string value changes.

Icarus Verilog 12.0 declares a Verilog ``real`` as ``$var real 1 ( r $end`` and
writes its value changes as ``r<number> (``, including ``rNaN`` inside the
``$dumpoff`` checkpoint. Rejecting those made every design with a real variable
unopenable.
"""

import unittest

import vcdtui


class RealValueTests(unittest.TestCase):
    TEXT = """\
$timescale 1 ns $end
$scope module top $end
$var reg 1 ! clk $end
$var real 1 " r $end
$var real 64 # rt $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
r1.5 "
r0 #
$end
#10
r2.25 "
r-3.5e-9 #
#20
$dumpoff
x!
rNaN "
rNaN #
$end
"""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(self.TEXT)

    def test_real_stream_kind(self):
        self.assertEqual(self.vcd.streams['"'].kind, "real")
        self.assertEqual(self.vcd.streams["!"].kind, "bit")

    def test_real_values_are_kept_verbatim(self):
        self.assertEqual(
            [(change.time, change.value) for change in self.vcd.streams['"'].changes],
            [(0, "1.5"), (10, "2.25"), (20, "NaN")],
        )
        self.assertEqual(
            [(change.time, change.value) for change in self.vcd.streams["#"].changes],
            [(0, "0"), (10, "-3.5e-9"), (20, "NaN")],
        )

    def test_real_values_are_not_width_normalized(self):
        # The 64-bit declaration must not zero-extend "0" into a bit vector.
        self.assertEqual(self.vcd.streams["#"].changes[0].value, "0")

    def test_real_value_is_displayed_verbatim(self):
        signal = next(s for s in self.vcd.signals if s.reference == "rt")
        for display_format in ("binary", "hex", "unsigned", "signed"):
            self.assertEqual(
                vcdtui.format_signal_value(signal, "-3.5e-9", display_format),
                "-3.5e-9",
            )

    def test_real_signal_renders_as_a_bus_track(self):
        signal = next(s for s in self.vcd.signals if s.reference == "r")
        track = vcdtui.render_waveform_track(signal, 0, 20, 24, ascii_only=True)
        self.assertIn("1.5", track)
        self.assertIn("|", track)

    def test_real_signal_has_no_edges(self):
        self.assertEqual(vcdtui.edge_times(self.vcd.streams['"'], "rising"), [])
        self.assertEqual(vcdtui.edge_times(self.vcd.streams['"'], "any"), [])

    def test_malformed_real_is_rejected(self):
        text = self.TEXT.replace('r1.5 "', 'rabc "')
        with self.assertRaisesRegex(vcdtui.VCDParseError, "invalid real value"):
            vcdtui.parse_vcd_text(text)


class StringValueTests(unittest.TestCase):
    TEXT = """\
$timescale 1 ns $end
$scope module top $end
$var string 1 ! state $end
$upscope $end
$enddefinitions $end
#0
sIDLE !
#10
sBUSY !
#20
s !
"""

    def setUp(self):
        self.vcd = vcdtui.parse_vcd_text(self.TEXT)

    def test_string_stream_kind(self):
        self.assertEqual(self.vcd.streams["!"].kind, "string")

    def test_string_values(self):
        self.assertEqual(
            [(change.time, change.value) for change in self.vcd.streams["!"].changes],
            [(0, "IDLE"), (10, "BUSY"), (20, "")],
        )

    def test_string_value_is_not_mistaken_for_x_or_z(self):
        signal = self.vcd.signals[0]
        self.assertEqual(vcdtui.format_signal_value(signal, "IDLE"), "IDLE")
        self.assertEqual(vcdtui._color_value(signal, "BUSY", True), "\x1b[36mBUSY\x1b[0m")


class UndeclaredKindTests(unittest.TestCase):
    HEADER = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! a $end
$upscope $end
$enddefinitions $end
"""

    def test_real_value_on_an_undeclared_real_var_is_accepted(self):
        # Some writers declare a real as a plain wire; the value form is
        # unambiguous, so adopt it instead of refusing to open the trace.
        vcd = vcdtui.parse_vcd_text(self.HEADER + "#0\nr1.25 !\n")
        self.assertEqual(vcd.streams["!"].kind, "real")
        self.assertEqual(vcd.streams["!"].changes[0].value, "1.25")

    def test_bit_value_on_a_real_var_is_rejected(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var real 1 ! r $end
$upscope $end
$enddefinitions $end
#0
b1010 !
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "real"):
            vcdtui.parse_vcd_text(text)


if __name__ == "__main__":
    unittest.main()
