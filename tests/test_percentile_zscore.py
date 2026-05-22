"""Tests for B1-4: percentile/z-score threshold infrastructure."""
import unittest
import numpy as np
import pandas as pd

from factors.base import BaseFactor


class DummyFactor(BaseFactor):
    def calculate(self):
        return {"factor_value": 1.0}


class RollingPercentileTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_percentile_low(self):
        series = pd.Series(range(100, 200))
        pct = self.factor._rolling_percentile(105, series, window=100)
        self.assertLess(pct, 10)

    def test_percentile_high(self):
        series = pd.Series(range(100, 200))
        pct = self.factor._rolling_percentile(195, series, window=100)
        self.assertGreater(pct, 90)

    def test_percentile_mid(self):
        series = pd.Series(range(100, 200))
        pct = self.factor._rolling_percentile(150, series, window=100)
        self.assertGreater(pct, 40)
        self.assertLess(pct, 60)

    def test_percentile_short_series(self):
        series = pd.Series([1.0, 2.0])
        pct = self.factor._rolling_percentile(1.5, series, window=100)
        self.assertEqual(pct, 50.0)  # neutral default


class RollingZscoreTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_zscore_positive(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        z = self.factor._rolling_zscore(130, series, window=200)
        self.assertGreater(z, 2.0)

    def test_zscore_negative(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        z = self.factor._rolling_zscore(70, series, window=200)
        self.assertLess(z, -2.0)

    def test_zscore_near_mean(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        z = self.factor._rolling_zscore(100, series, window=200)
        self.assertAlmostEqual(z, 0.0, delta=0.5)

    def test_zscore_short_series(self):
        series = pd.Series([1.0, 2.0])
        z = self.factor._rolling_zscore(1.5, series, window=100)
        self.assertEqual(z, 0.0)  # neutral default


class PercentileSignalTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_buy_at_low_percentile(self):
        series = pd.Series(range(100, 200))
        sig = self.factor._percentile_signal(105, series, low_pct=20, high_pct=80)
        self.assertEqual(sig, "BUY")

    def test_sell_at_high_percentile(self):
        series = pd.Series(range(100, 200))
        sig = self.factor._percentile_signal(195, series, low_pct=20, high_pct=80)
        self.assertEqual(sig, "SELL")

    def test_hold_at_mid(self):
        series = pd.Series(range(100, 200))
        sig = self.factor._percentile_signal(150, series, low_pct=20, high_pct=80)
        self.assertEqual(sig, "HOLD")


class ZscoreSignalTest(unittest.TestCase):
    def setUp(self):
        from core.data_bus import DataBus
        DataBus.reset()
        self.factor = DummyFactor(data_dir="/tmp/nonexistent")

    def test_buy_at_extreme_low(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        sig = self.factor._zscore_signal(70, series, buy_z=-2.0, sell_z=2.0)
        self.assertEqual(sig, "BUY")

    def test_sell_at_extreme_high(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        sig = self.factor._zscore_signal(130, series, buy_z=-2.0, sell_z=2.0)
        self.assertEqual(sig, "SELL")

    def test_hold_near_mean(self):
        np.random.seed(42)
        series = pd.Series(np.random.normal(100, 10, 200))
        sig = self.factor._zscore_signal(100, series, buy_z=-2.0, sell_z=2.0)
        self.assertEqual(sig, "HOLD")


if __name__ == "__main__":
    unittest.main()
