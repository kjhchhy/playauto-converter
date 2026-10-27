import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.pricing import (
    calculate_base_payout,
    ceil_to_100,
    final_sale_price,
    parse_commission_percent,
    parse_margin_ratio,
)


class PricingTests(unittest.TestCase):
    def test_ceil_to_100_rounds_up_to_next_hundred(self):
        self.assertEqual(ceil_to_100(9465.24), 9500)
        self.assertEqual(ceil_to_100(8861), 8900)
        self.assertEqual(ceil_to_100(0), 0)

    def test_parse_margin_ratio_accepts_fraction_and_percent(self):
        self.assertEqual(parse_margin_ratio(0.15), 0.15)
        self.assertEqual(parse_margin_ratio(15), 0.15)
        self.assertEqual(parse_margin_ratio("15%"), 0.15)
        self.assertIsNone(parse_margin_ratio(None))
        self.assertIsNone(parse_margin_ratio(""))

    def test_parse_commission_percent_normalizes_fraction(self):
        self.assertEqual(parse_commission_percent(12), 12.0)
        self.assertEqual(parse_commission_percent(0.12), 12.0)
        self.assertEqual(parse_commission_percent("12%"), 12.0)

    def test_calculate_base_payout_removes_margin(self):
        self.assertAlmostEqual(calculate_base_payout(7080, 0.15), 8329.411764705883)
        self.assertAlmostEqual(calculate_base_payout(7080, 15), 8329.411764705883)
        self.assertAlmostEqual(calculate_base_payout(7080, 1), 7151.515151515152)
        self.assertIsNone(calculate_base_payout(7080, 100))
        self.assertIsNone(calculate_base_payout(7080, -0.1))

    def test_final_sale_price_applies_commission_and_ceil(self):
        self.assertEqual(final_sale_price(7080, 0.15, 12), 9500)
        self.assertEqual(final_sale_price(7080, 0.15, 6), 8900)


if __name__ == "__main__":
    unittest.main()
