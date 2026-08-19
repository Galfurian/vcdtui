import unittest

import vcdtui


class VCDSubsetTests(unittest.TestCase):
    def test_identifier_is_opaque(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ~! strange $end
$upscope $end
$enddefinitions $end
#0
0~!
#1
1~!
"""
        vcd = vcdtui.parse_vcd_text(text)
        self.assertIn("~!", vcd.streams)
        self.assertEqual([c.value for c in vcd.streams["~!"].changes], ["0", "1"])

    def test_multiline_directives(self):
        text = """\
$timescale
  100
  fs
$end
$scope
 module
 top
$end
$var
 wire
 1
 !
 clk
$end
$upscope
$end
$enddefinitions
$end
#0 0!
"""
        vcd = vcdtui.parse_vcd_text(text)
        self.assertEqual(vcd.timescale.coefficient, 100)
        self.assertEqual(vcd.timescale.unit, "fs")
        self.assertEqual(vcd.signals[0].full_name, "top.clk")

    def test_unclosed_scope_rejected(self):
        text = """\
$timescale 1 ns $end
$scope module top $end
$var wire 1 ! clk $end
$enddefinitions $end
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "unclosed"):
            vcdtui.parse_vcd_text(text)

    def test_unknown_directive_rejected(self):
        text = """\
$timescale 1 ns $end
$foo bar $end
$enddefinitions $end
"""
        with self.assertRaisesRegex(vcdtui.VCDParseError, "unsupported header directive"):
            vcdtui.parse_vcd_text(text)


if __name__ == "__main__":
    unittest.main()
