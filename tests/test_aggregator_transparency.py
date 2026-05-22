"""Tests for signal aggregator transparency features (A2-1)."""
import unittest
from core.signal_aggregator import SignalAggregator


class AggregatorTransparencyTest(unittest.TestCase):
    def test_aggregate_returns_transparency_fields(self):
        signals = [
            {"direction": "BUY", "strength": 0.8, "confidence": 0.7, "trigger": "t1"},
            {"direction": "BUY", "strength": 0.6, "confidence": 0.6, "trigger": "t2"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        self.assertEqual(result["raw_signal_count"], 2)
        self.assertEqual(result["effective_signal_count"], 2)
        self.assertFalse(result["dedup_applied"])
        self.assertIn("driver_groups", result)
        self.assertIn("conflict_score", result)

    def test_conflict_score_zero_when_unanimous(self):
        signals = [
            {"direction": "BUY", "strength": 0.8, "confidence": 0.7, "trigger": "t1"},
            {"direction": "BUY", "strength": 0.6, "confidence": 0.6, "trigger": "t2"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        self.assertEqual(result["conflict_score"], 0.0)

    def test_conflict_score_high_when_split(self):
        signals = [
            {"direction": "BUY", "strength": 0.8, "confidence": 0.7, "trigger": "t1"},
            {"direction": "SELL", "strength": 0.8, "confidence": 0.7, "trigger": "t2"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        self.assertGreater(result["conflict_score"], 0.8)

    def test_conflict_score_partial_conflict(self):
        signals = [
            {"direction": "BUY", "strength": 0.8, "confidence": 0.7, "trigger": "t1"},
            {"direction": "BUY", "strength": 0.6, "confidence": 0.6, "trigger": "t2"},
            {"direction": "SELL", "strength": 0.3, "confidence": 0.4, "trigger": "t3"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        self.assertGreater(result["conflict_score"], 0.0)
        self.assertLess(result["conflict_score"], 1.0)

    def test_driver_groups_ungrouped(self):
        signals = [
            {"direction": "BUY", "strength": 0.5, "confidence": 0.5, "trigger": "alpha"},
            {"direction": "SELL", "strength": 0.5, "confidence": 0.5, "trigger": "beta"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        groups = result["driver_groups"]
        self.assertIn("ungrouped", groups)
        self.assertEqual(len(groups["ungrouped"]), 2)

    def test_driver_groups_with_dedup_group(self):
        signals = [
            {"direction": "BUY", "strength": 0.5, "confidence": 0.5, "trigger": "t1", "dedup_group": "growth"},
            {"direction": "BUY", "strength": 0.5, "confidence": 0.5, "trigger": "t2", "dedup_group": "growth"},
            {"direction": "SELL", "strength": 0.5, "confidence": 0.5, "trigger": "t3", "dedup_group": "inflation"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        groups = result["driver_groups"]
        self.assertEqual(len(groups["growth"]), 2)
        self.assertEqual(len(groups["inflation"]), 1)

    def test_aggregate_none_for_empty(self):
        self.assertIsNone(SignalAggregator.aggregate([]))
        self.assertIsNone(SignalAggregator.aggregate([None]))

    def test_raw_vs_effective_with_dedup(self):
        signals = [
            {"direction": "BUY", "strength": 0.8, "confidence": 0.7, "trigger": "momentum_5d"},
            {"direction": "BUY", "strength": 0.6, "confidence": 0.6, "trigger": "momentum_20d"},
        ]
        # With dedup enabled, if correlation_groups are configured, effective may differ
        result = SignalAggregator.aggregate(signals, dedup=True)
        self.assertEqual(result["raw_signal_count"], 2)
        self.assertGreaterEqual(result["effective_signal_count"], 1)


if __name__ == "__main__":
    unittest.main()
