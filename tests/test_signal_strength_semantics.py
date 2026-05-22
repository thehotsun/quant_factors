"""Tests for B0-2: signal_strength semantic split."""
import unittest
from factors.base import BaseFactor
from core.signal_aggregator import SignalAggregator


class DummyFactor(BaseFactor):
    def calculate(self):
        return {"factor_value": 1.0}

    def signal(self):
        return self._make_signal(
            asset="Test", direction="BUY", reason="test",
            strength=0.6, confidence=0.7,
            factor_score=1.5, risk_modifier=0.8,
        )

    def signal_sell(self):
        return self._make_signal(
            asset="Test", direction="SELL", reason="test sell",
            strength=-0.6, confidence=0.7,
            factor_score=-1.5, risk_modifier=0.8,
        )


class MakeSignalSemanticTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_buy_signal_has_positive_trade_strength(self):
        sig = self.factor.signal()
        self.assertEqual(sig["direction"], "BUY")
        self.assertGreater(sig["trade_signal_strength"], 0)
        self.assertAlmostEqual(sig["trade_signal_strength"], 0.6, places=2)

    def test_sell_signal_has_negative_trade_strength(self):
        sig = self.factor.signal_sell()
        self.assertEqual(sig["direction"], "SELL")
        self.assertLess(sig["trade_signal_strength"], 0)
        self.assertAlmostEqual(sig["trade_signal_strength"], -0.6, places=2)

    def test_factor_score_preserved(self):
        sig = self.factor.signal()
        self.assertEqual(sig["factor_score"], 1.5)

    def test_risk_modifier_preserved(self):
        sig = self.factor.signal()
        self.assertEqual(sig["risk_modifier"], 0.8)

    def test_strength_backward_compatible(self):
        sig = self.factor.signal()
        self.assertIn("strength", sig)
        self.assertIn("signal_strength", sig)
        self.assertEqual(sig["strength"], sig["signal_strength"])

    def test_buy_with_negative_strength_still_positive_trade(self):
        """Even if raw strength is negative, BUY direction makes trade_signal_strength positive."""
        sig = self.factor._make_signal(
            asset="X", direction="BUY", reason="test",
            strength=-0.3, confidence=0.5,
        )
        self.assertGreaterEqual(sig["trade_signal_strength"], 0)

    def test_sell_with_positive_strength_still_negative_trade(self):
        """Even if raw strength is positive, SELL direction makes trade_signal_strength negative."""
        sig = self.factor._make_signal(
            asset="X", direction="SELL", reason="test",
            strength=0.3, confidence=0.5,
        )
        self.assertLessEqual(sig["trade_signal_strength"], 0)


class AggregatorUsesTradeSignalStrengthTest(unittest.TestCase):
    def test_aggregator_prefers_trade_signal_strength(self):
        signals = [
            {"direction": "BUY", "strength": 0.3, "trade_signal_strength": 0.8,
             "confidence": 0.7, "trigger": "t1"},
            {"direction": "SELL", "strength": -0.5, "trade_signal_strength": -0.4,
             "confidence": 0.6, "trigger": "t2"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        # t1 has trade_signal_strength 0.8, t2 has -0.4
        # BUY side dominates → direction should be BUY
        self.assertEqual(result["direction"], "BUY")

    def test_aggregator_falls_back_to_strength(self):
        """If trade_signal_strength is not present, use raw strength."""
        signals = [
            {"direction": "BUY", "strength": 0.6, "confidence": 0.7, "trigger": "t1"},
        ]
        result = SignalAggregator.aggregate(signals, dedup=False)
        self.assertEqual(result["direction"], "BUY")
        self.assertGreater(result["strength"], 0)


if __name__ == "__main__":
    unittest.main()
