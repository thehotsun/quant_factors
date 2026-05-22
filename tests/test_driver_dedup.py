"""Tests for B1-3: driver-based dedup in aggregator."""
import unittest
from core.signal_aggregator import SignalAggregator


class DriverClassificationTest(unittest.TestCase):
    def test_classifies_growth(self):
        self.assertEqual(SignalAggregator._classify_driver("pmi_copper_divergence"), "growth")
        self.assertEqual(SignalAggregator._classify_driver("pmi_expansion_aluminum"), "growth")

    def test_classifies_inflation(self):
        self.assertEqual(SignalAggregator._classify_driver("cpi_gold_surge"), "inflation")
        self.assertEqual(SignalAggregator._classify_driver("oil_inflation_gold"), "inflation")

    def test_classifies_risk_off(self):
        self.assertEqual(SignalAggregator._classify_driver("vix_panic_gold"), "risk_off")

    def test_classifies_fx(self):
        self.assertEqual(SignalAggregator._classify_driver("forex_commodity_buy"), "fx")

    def test_classifies_cost(self):
        self.assertEqual(SignalAggregator._classify_driver("feed_cost_high"), "cost")
        self.assertEqual(SignalAggregator._classify_driver("iron_ore_surge"), "cost")

    def test_classifies_seasonality(self):
        self.assertEqual(SignalAggregator._classify_driver("seasonal_gas_winter"), "seasonality")

    def test_classifies_other_for_unknown(self):
        self.assertEqual(SignalAggregator._classify_driver("some_random_trigger"), "other")

    def test_classifies_empty(self):
        self.assertEqual(SignalAggregator._classify_driver(""), "other")


class DriverDedupTest(unittest.TestCase):
    def test_no_dedup_for_single_signal(self):
        signals = [{"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "pmi_copper"}]
        result = SignalAggregator._dedup_drivers(signals)
        self.assertEqual(len(result), 1)
        self.assertNotIn("driver_dedup_group", result[0])

    def test_no_dedup_for_different_drivers(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "pmi_copper"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "vix_panic"},
        ]
        result = SignalAggregator._dedup_drivers(signals)
        # growth vs risk_off → different drivers, no dedup
        self.assertNotIn("driver_dedup_group", result[0])
        self.assertNotIn("driver_dedup_group", result[1])

    def test_dedup_same_driver(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "pmi_copper"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "pmi_aluminum"},
        ]
        result = SignalAggregator._dedup_drivers(signals)
        # Both growth → 1/sqrt(2) decay
        import numpy as np
        decay = 1.0 / np.sqrt(2)
        self.assertAlmostEqual(result[0]["strength"], 0.6 * decay, places=3)
        self.assertAlmostEqual(result[1]["strength"], 0.5 * decay, places=3)
        self.assertEqual(result[0]["driver_dedup_group"], "growth")
        self.assertEqual(result[1]["driver_dedup_group"], "growth")

    def test_dedup_preserves_driver_from_signal(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "t1", "driver": "growth"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "t2", "driver": "growth"},
        ]
        result = SignalAggregator._dedup_drivers(signals)
        self.assertEqual(result[0]["driver"], "growth")

    def test_three_same_driver_stronger_decay(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "pmi_copper"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "pmi_aluminum"},
            {"direction": "BUY", "strength": 0.4, "confidence": 0.5, "trigger": "pmi_steel"},
        ]
        result = SignalAggregator._dedup_drivers(signals)
        import numpy as np
        decay = 1.0 / np.sqrt(3)
        for r in result:
            self.assertIn("driver_dedup_group", r)
            self.assertAlmostEqual(r["driver_dedup_factor"], decay, places=3)


class AggregatorDriverIntegrationTest(unittest.TestCase):
    def test_full_pipeline_with_driver_dedup(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "pmi_copper"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "pmi_aluminum"},
            {"direction": "SELL", "strength": -0.4, "confidence": 0.5, "trigger": "vix_panic"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=True)
        self.assertIn("driver_groups", result)
        # growth driver should have 2 signals, risk_off should have 1
        groups = result["driver_groups"]
        growth_count = len(groups.get("growth", []))
        self.assertEqual(growth_count, 2)

    def test_driver_groups_in_output(self):
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "feed_cost_high"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.6, "trigger": "iron_ore_surge"},
            {"direction": "BUY", "strength": 0.4, "confidence": 0.5, "trigger": "seasonal_gas"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        groups = result["driver_groups"]
        self.assertIn("cost", groups)
        self.assertIn("seasonality", groups)


if __name__ == "__main__":
    unittest.main()
