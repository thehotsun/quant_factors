"""Tests for evaluation/trigger_backtest.py (B0-1)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from evaluation.trigger_backtest import (
    _build_asset_to_dep,
    _get_forward_returns,
    _aggregate_trigger_stats,
    trigger_backtest,
    format_trigger_report,
)


class BuildAssetToDepTest(unittest.TestCase):
    def test_maps_asset_to_first_dep(self):
        chains = {
            "a": {"asset": "铜期货(CU)", "data_deps": ["copper_futures", "pmi"]},
            "b": {"asset": "黄金期货(AU)", "data_deps": ["gold_futures"]},
        }
        m = _build_asset_to_dep(chains)
        self.assertEqual(m["铜期货(CU)"], "copper_futures")
        self.assertEqual(m["黄金期货(AU)"], "gold_futures")

    def test_first_wins_on_duplicate_asset(self):
        chains = {
            "a": {"asset": "X", "data_deps": ["dep1"]},
            "b": {"asset": "X", "data_deps": ["dep2"]},
        }
        m = _build_asset_to_dep(chains)
        self.assertEqual(m["X"], "dep1")

    def test_skips_empty_asset(self):
        chains = {"a": {"asset": "", "data_deps": ["dep1"]}}
        m = _build_asset_to_dep(chains)
        self.assertEqual(m, {})


class ForwardReturnsTest(unittest.TestCase):
    def test_calculates_forward_returns(self):
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="D"),
            "close": [100.0 + i for i in range(30)],
        })
        result = _get_forward_returns(df, "2024-01-05")
        self.assertAlmostEqual(result["fwd_1d"], 1.0 / 104.0, places=4)
        self.assertAlmostEqual(result["fwd_5d"], 5.0 / 104.0, places=4)

    def test_returns_none_for_missing_dates(self):
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
        })
        result = _get_forward_returns(df, "2024-12-01")
        for v in result.values():
            self.assertIsNone(v)

    def test_returns_none_for_empty_df(self):
        result = _get_forward_returns(pd.DataFrame(), "2024-01-01")
        for v in result.values():
            self.assertIsNone(v)

    def test_returns_none_at_end_of_data(self):
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
        })
        result = _get_forward_returns(df, "2024-01-05")
        self.assertIsNone(result["fwd_1d"])
        self.assertIsNone(result["fwd_5d"])


class AggregateStatsTest(unittest.TestCase):
    def test_basic_aggregation(self):
        records = [
            {"direction": "BUY", "fwd_1d": 0.01, "fwd_5d": 0.03, "fwd_10d": 0.05, "fwd_20d": 0.08, "year": 2024},
            {"direction": "BUY", "fwd_1d": -0.01, "fwd_5d": -0.02, "fwd_10d": -0.03, "fwd_20d": -0.04, "year": 2024},
            {"direction": "BUY", "fwd_1d": 0.02, "fwd_5d": 0.04, "fwd_10d": 0.06, "fwd_20d": 0.10, "year": 2025},
        ]
        stats = _aggregate_trigger_stats(records)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["buy_count"], 3)
        self.assertAlmostEqual(stats["avg_fwd_5d"], (0.03 - 0.02 + 0.04) / 3, places=4)
        self.assertAlmostEqual(stats["win_rate_fwd_5d"], 2 / 3, places=2)
        self.assertIn("by_year", stats)

    def test_sell_direction_win_rate(self):
        records = [
            {"direction": "SELL", "fwd_1d": -0.02, "fwd_5d": -0.05, "fwd_10d": -0.08, "fwd_20d": -0.10, "year": 2024},
            {"direction": "SELL", "fwd_1d": 0.01, "fwd_5d": 0.02, "fwd_10d": 0.03, "fwd_20d": 0.04, "year": 2024},
        ]
        stats = _aggregate_trigger_stats(records)
        # SELL with negative return = win (direction-adjusted)
        self.assertAlmostEqual(stats["win_rate_fwd_5d"], 0.5, places=2)

    def test_empty_records(self):
        stats = _aggregate_trigger_stats([])
        self.assertEqual(stats["count"], 0)


class TriggerBacktestIntegrationTest(unittest.TestCase):
    def test_end_to_end(self):
        chains = {"copper": {"asset": "铜期货(CU)", "data_deps": ["copper_futures"]}}
        price_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="D"),
            "close": [100.0 + i * 0.5 for i in range(30)],
        })
        data_bus = MagicMock()
        data_bus.get.return_value = price_df

        signal_logger = MagicMock()
        signal_logger.query.return_value = [
            {"trigger": "pmi_copper", "asset": "铜期货(CU)", "direction": "BUY",
             "as_of": "2024-01-05", "strength": 0.6, "confidence": 0.7, "reason": "test1"},
            {"trigger": "pmi_copper", "asset": "铜期货(CU)", "direction": "BUY",
             "as_of": "2024-01-10", "strength": 0.5, "confidence": 0.6, "reason": "test2"},
            {"trigger": "pmi_copper", "asset": "铜期货(CU)", "direction": "BUY",
             "as_of": "2024-01-15", "strength": 0.7, "confidence": 0.8, "reason": "test3"},
        ]

        report = trigger_backtest(chains, data_bus, signal_logger, days=30, min_samples=2)
        self.assertEqual(report["summary"]["triggers_evaluated"], 1)
        self.assertIn("pmi_copper", report["triggers"])
        self.assertEqual(report["triggers"]["pmi_copper"]["count"], 3)

    def test_skips_insufficient_samples(self):
        chains = {}
        data_bus = MagicMock()
        signal_logger = MagicMock()
        signal_logger.query.return_value = [
            {"trigger": "rare_trigger", "asset": "X", "direction": "BUY", "as_of": "2024-01-01"},
        ]
        report = trigger_backtest(chains, data_bus, signal_logger, days=30, min_samples=5)
        self.assertTrue(report["triggers"]["rare_trigger"]["insufficient_samples"])

    def test_empty_signals(self):
        signal_logger = MagicMock()
        signal_logger.query.return_value = []
        report = trigger_backtest({}, MagicMock(), signal_logger)
        self.assertEqual(report["summary"]["total_signals"], 0)


class FormatReportTest(unittest.TestCase):
    def test_format_report(self):
        report = {
            "summary": {"total_signals": 10, "unique_triggers": 2, "triggers_evaluated": 1,
                        "triggers_insufficient": 1, "lookback_days": 365, "min_samples": 3},
            "triggers": {
                "good_trigger": {
                    "count": 8, "buy_count": 6, "sell_count": 2,
                    "avg_fwd_5d": 0.02, "win_rate_fwd_5d": 0.75,
                    "avg_fwd_20d": 0.05, "win_rate_fwd_20d": 0.7,
                    "max_loss_fwd_5d": -0.03, "description": "test", "asset": "铜",
                },
                "rare_trigger": {"count": 1, "insufficient_samples": True, "min_required": 3},
            },
        }
        md = format_trigger_report(report)
        self.assertIn("good_trigger", md)
        self.assertIn("75%", md)
        self.assertIn("rare_trigger", md)


if __name__ == "__main__":
    unittest.main()
