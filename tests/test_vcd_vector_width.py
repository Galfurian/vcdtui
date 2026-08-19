"""Vector width normalization, and recognising extended VCD."""

import unittest

import vcdtui


HEADER = """\
$timescale 1 ns $end
$scope module top $end
$var wire 4 ! bus $end
$upscope $end
$enddefinitions $end
"""


class VectorWidthTests(unittest.TestCase):
    def value(self, literal):
        vcd = vcdtui.parse_vcd_text(HEADER + f"#0\n{literal} !\n")
        return vcd.streams["!"].changes[0].value

    def test_exact_width_is_kept(self):
        self.assertEqual(self.value("b1010"), "1010")

    def test_short_value_is_zero_extended(self):
        self.assertEqual(self.value("b1"), "0001")

    def test_short_value_starting_in_x_is_x_extended(self):
        self.assertEqual(self.value("bx"), "xxxx")
        self.assertEqual(self.value("bz"), "zzzz")

    def test_redundant_leading_zeros_are_dropped(self):
        # IEEE 1364 sizes a value to the variable; writers padding beyond the
        # declared width lose nothing, so the trace should still open.
        self.assertEqual(self.value("b000001010"), "1010")

    def test_redundant_leading_x_is_dropped(self):
        self.assertEqual(self.value("bxxxxxx"), "xxxx")

    def test_significant_bits_beyond_the_width_are_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "exceeds declared width 4"):
            self.value("b111110101")

    def test_mixed_state_overflow_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "exceeds declared width 4"):
            self.value("bxxxx1010")

    def test_non_binary_digits_are_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "unsupported binary vector"):
            self.value("b1092")

    def test_empty_vector_is_rejected(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "unsupported binary vector"):
            self.value("b")

    def test_uppercase_states_are_normalized(self):
        self.assertEqual(self.value("B1X0Z"), "1x0z")


class ExtendedVCDTests(unittest.TestCase):
    def test_port_declaration_is_named_as_evcd(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var port 1 <0 clk $end
$upscope $end
$enddefinitions $end
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "extended VCD"):
            vcdtui.parse_vcd_text(text)

    def test_dumpports_is_named_as_evcd(self):
        with self.assertRaisesRegex(vcdtui.VCDParseError, "extended VCD"):
            vcdtui.parse_vcd_text(HEADER + "#0\n$dumpports\n$end\n")


if __name__ == "__main__":
    unittest.main()
