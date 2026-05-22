"""Tests for B1-1: volatility-calibrated stop-loss."""
import unittest
import numpy as np
import pandas as pd

from factors.base import BaseFactor


class DummyFactor(BaseFactor):
    def calculate(self):
        return {"factor_value": 1.0}


class RealizedVolTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_computes_annualized_vol(self):
        np.random.seed(42)
        returns = np.random.normal(0, 0.02, 100)
        prices = 100 * np.cumprod(1 + returns)
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=100), "close": prices})
        vol = self.factor._realized_vol(df, window=20)
        self.assertIsNotNone(vol)
        # 2% daily vol * sqrt(252) ≈ 31.7%
        self.assertGreater(vol, 0.1)
        self.assertLess(vol, 1.0)

    def test_returns_none_for_short_series(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        vol = self.factor._realized_vol(df, window=20)
        self.assertIsNone(vol)

    def test_returns_none_for_constant_price(self):
        df = pd.DataFrame({"close": [100.0] * 30})
        vol = self.factor._realized_vol(df, window=20)
        self.assertIsNone(vol)


class VolatilityStopTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_stop_scales_with_vol(self):
        low_vol = pd.DataFrame({"close": [100.0 + i * 0.01 for i in range(30)]})
        high_vol = pd.DataFrame({"close": [100.0 + np.sin(i) * 5 for i in range(30)]})
        stop_low = self.factor._volatility_stop(low_vol, holding_days=5)
        stop_high = self.factor._volatility_stop(high_vol, holding_days=5)
        self.assertIsNotNone(stop_low)
        self.assertIsNotNone(stop_high)
        # Higher vol → wider stop (more negative)
        self.assertLess(stop_high, stop_low)

    def test_stop_scales_with_holding_days(self):
        df = pd.DataFrame({"close": [100.0 + np.sin(i) * 2 for i in range(30)]})
        stop_5d = self.factor._volatility_stop(df, holding_days=5)
        stop_20d = self.factor._volatility_stop(df, holding_days=20)
        self.assertIsNotNone(stop_5d)
        self.assertIsNotNone(stop_20d)
        # Longer holding → wider stop
        self.assertLess(stop_20d, stop_5d)

    def test_stop_capped_at_minus_15pct(self):
        # Extreme volatility
        np.random.seed(42)
        returns = np.random.normal(0, 0.10, 100)
        prices = 100 * np.cumprod(1 + returns)
        df = pd.DataFrame({"close": prices})
        stop = self.factor._volatility_stop(df, holding_days=30)
        self.assertIsNotNone(stop)
        self.assertGreaterEqual(stop, -0.15)

    def test_stop_always_negative(self):
        df = pd.DataFrame({"close": [100.0 + i * 0.5 for i in range(30)]})
        stop = self.factor._volatility_stop(df, holding_days=10)
        self.assertIsNotNone(stop)
        self.assertLess(stop, 0)

    def test_returns_none_for_short_data(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        stop = self.factor._volatility_stop(df, holding_days=5)
        self.assertIsNone(stop)


class MakeSignalVolStopTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_make_signal_uses_vol_stop_when_price_df_provided(self):
        df = pd.DataFrame({"close": [100.0 + np.sin(i) * 3 for i in range(30)]})
        sig = self.factor._make_signal(
            asset="Test", direction="BUY", reason="test",
            holding_days=10, stop_loss=-0.02,  # default
            price_df=df,
        )
        # Should be replaced by vol-calibrated stop
        self.assertNotEqual(sig["stop_loss"], -0.02)
        self.assertLess(sig["stop_loss"], 0)

    def test_make_signal_keeps_default_without_price_df(self):
        sig = self.factor._make_signal(
            asset="Test", direction="BUY", reason="test",
            holding_days=10, stop_loss=-0.02,
        )
        self.assertEqual(sig["stop_loss"], -0.02)

    def test_make_signal_keeps_default_for_short_data(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        sig = self.factor._make_signal(
            asset="Test", direction="BUY", reason="test",
            holding_days=5, stop_loss=-0.02,
            price_df=df,
        )
        # Short data → _volatility_stop returns None → keep default
        self.assertEqual(sig["stop_loss"], -0.02)


if __name__ == "__main__":
    unittest.main()
