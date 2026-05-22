"""Tests for B2-2: IC evaluation by factor type."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.ic_monitor import ICMonitor


class DirectionHitRateTest(unittest.TestCase):
    def setUp(self):
        ICMonitor._instance = None
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "ic.db"
        self.mon = ICMonitor(str(self.db_path))

    def tearDown(self):
        ICMonitor._instance = None

    def _seed_snapshots(self, factor_name, dates, values):
        for d, v in zip(dates, values):
            self.mon.snapshot(factor_name, v, snapshot_date=d)

    def test_perfect_positive_factor(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="D").strftime("%Y-%m-%d").tolist()
        values = [1.0] * 30  # always positive → always "up"
        self._seed_snapshots("test_factor", dates, values)

        prices = 100 + np.arange(40) * 0.5 + np.random.RandomState(42).normal(0, 0.01, 40)
        price_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "close": prices,
        })

        result = self.mon.compute_direction_hit_rate("test_factor", price_df, forward_days=5)
        self.assertIsNotNone(result)
        self.assertGreater(result["hit_rate"], 0.5)
        self.assertEqual(result["method"], "direction_hit_rate")

    def test_returns_none_for_insufficient_data(self):
        price_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [100, 101, 102, 103, 104],
        })
        result = self.mon.compute_direction_hit_rate("no_data", price_df)
        self.assertIsNone(result)


class EvaluateFactorTest(unittest.TestCase):
    def setUp(self):
        ICMonitor._instance = None
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "ic.db"
        self.mon = ICMonitor(str(self.db_path))

    def tearDown(self):
        ICMonitor._instance = None

    def test_evaluate_time_series_factor(self):
        # Seed enough snapshots for IC computation
        dates = pd.date_range("2024-01-01", periods=80, freq="D").strftime("%Y-%m-%d").tolist()
        np.random.seed(42)
        values = np.random.normal(0, 1, 80).tolist()
        for d, v in zip(dates, values):
            self.mon.snapshot("test_ts", v, snapshot_date=d)

        prices = 100 + np.cumsum(np.random.RandomState(42).normal(0, 1, 100))
        price_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "close": prices,
        })

        result = self.mon.evaluate_factor("test_ts", price_df, factor_type="time_series")
        self.assertIn("factor_name", result)
        # Should have IC or error
        self.assertTrue("ic" in result or "error" in result)

    def test_evaluate_trigger_factor(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="D").strftime("%Y-%m-%d").tolist()
        values = [0.5] * 30
        for d, v in zip(dates, values):
            self.mon.snapshot("test_trigger", v, snapshot_date=d)

        prices = 100 + np.arange(40) * 0.5 + np.random.RandomState(42).normal(0, 0.01, 40)
        price_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "close": prices,
        })

        result = self.mon.evaluate_factor("test_trigger", price_df, factor_type="trigger")
        self.assertEqual(result.get("method"), "direction_hit_rate")

    def test_evaluate_cross_sectional_returns_not_supported(self):
        price_df = pd.DataFrame({"close": [100.0]})
        result = self.mon.evaluate_factor("test_xs", price_df, factor_type="cross_sectional")
        self.assertIn("not supported", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
