"""Tests for B2-1: regime filter infrastructure."""
import unittest
import numpy as np
import pandas as pd

from factors.base import BaseFactor


class DummyFactor(BaseFactor):
    def calculate(self):
        return {"factor_value": 1.0}


class RegimeConfidenceModifierTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_high_vix_boosts_risk_off(self):
        regime = {"vix": 35, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "risk_off")
        self.assertGreater(mult, 1.0)
        self.assertIn("恐慌", explanation)
        self.assertIn("避险", explanation)

    def test_high_vix_dampens_risk_on(self):
        regime = {"vix": 35, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "risk_on")
        self.assertLess(mult, 1.0)
        self.assertIn("恐慌", explanation)

    def test_low_vix_boosts_risk_on(self):
        regime = {"vix": 12, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0}
        mult, _ = self.factor._regime_confidence_modifier(regime, "risk_on")
        self.assertGreater(mult, 1.0)

    def test_low_vix_dampens_risk_off(self):
        regime = {"vix": 12, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0}
        mult, _ = self.factor._regime_confidence_modifier(regime, "risk_off")
        self.assertLess(mult, 1.0)

    def test_pmi_expanding_boosts_industrial(self):
        regime = {"vix": 20, "pmi": 52, "pmi_change": 1.5, "usd_cny_5d_change": 0}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "industrial")
        self.assertGreater(mult, 1.0)
        self.assertIn("扩张", explanation)

    def test_pmi_contracting_dampens_industrial(self):
        regime = {"vix": 20, "pmi": 48, "pmi_change": -1.5, "usd_cny_5d_change": 0}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "industrial")
        self.assertLess(mult, 1.0)
        self.assertIn("收缩", explanation)

    def test_rmb_depreciation_boosts_fx_cost(self):
        regime = {"vix": 20, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0.015}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "fx_cost")
        self.assertGreater(mult, 1.0)
        self.assertIn("贬", explanation)

    def test_rmb_appreciation_dampens_fx_cost(self):
        regime = {"vix": 20, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": -0.015}
        mult, explanation = self.factor._regime_confidence_modifier(regime, "fx_cost")
        self.assertLess(mult, 1.0)
        self.assertIn("升", explanation)

    def test_neutral_regime_no_change(self):
        regime = {"vix": 20, "pmi": 50, "pmi_change": 0, "usd_cny_5d_change": 0}
        mult, _ = self.factor._regime_confidence_modifier(regime, "neutral")
        self.assertEqual(mult, 1.0)

    def test_none_values_handled(self):
        regime = {"vix": None, "pmi": None, "pmi_change": None, "usd_cny_5d_change": None}
        mult, _ = self.factor._regime_confidence_modifier(regime, "risk_off")
        self.assertEqual(mult, 1.0)

    def test_multiplier_capped(self):
        # Extreme VIX + PMI + FX all favorable
        regime = {"vix": 50, "pmi": 55, "pmi_change": 3.0, "usd_cny_5d_change": 0.03}
        mult, _ = self.factor._regime_confidence_modifier(regime, "risk_off")
        self.assertLessEqual(mult, 1.2)

    def test_multiplier_floored(self):
        # All unfavorable
        regime = {"vix": 10, "pmi": 45, "pmi_change": -2.0, "usd_cny_5d_change": -0.02}
        mult, _ = self.factor._regime_confidence_modifier(regime, "risk_off")
        self.assertGreaterEqual(mult, 0.5)


if __name__ == "__main__":
    unittest.main()
