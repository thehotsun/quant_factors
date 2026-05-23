import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from download_history import save_parquet
from scripts.audit_chains import audit_chains


class DataRefreshSafetyTest(unittest.TestCase):
    def test_save_parquet_does_not_overwrite_existing_file_with_empty_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            existing = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [123.0]})
            existing.to_parquet(data_dir / "sample.parquet", index=False)

            with patch("download_history.DATA_DIR", data_dir):
                save_parquet(pd.DataFrame(), "sample")

            result = pd.read_parquet(data_dir / "sample.parquet")
            self.assertEqual(len(result), 1)
            self.assertEqual(float(result.loc[0, "close"]), 123.0)

    def test_save_parquet_writes_atomically_and_normalizes_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            df = pd.DataFrame({"日期": ["2024-01-02", "2024-01-01"], "收盘": [11.0, 10.0]})

            with patch("download_history.DATA_DIR", data_dir):
                save_parquet(df, "sample")

            result = pd.read_parquet(data_dir / "sample.parquet")
            self.assertEqual(list(result.columns), ["date", "close"])
            self.assertEqual(result["date"].dt.strftime("%Y-%m-%d").tolist(), ["2024-01-01", "2024-01-02"])
            self.assertEqual(result["close"].tolist(), [10.0, 11.0])
            self.assertFalse((data_dir / "sample.parquet.tmp").exists())

    def test_audit_classifies_known_missing_dependencies(self):
        report = audit_chains(run_calculate=False)
        summary = report["summary"]
        self.assertEqual(summary["unexpected_missing_deps"], 0)
        self.assertGreaterEqual(summary["known_missing_deps"], 1)

        known = {
            (item["chain"], dep)
            for item in report["chains"]
            for dep in item.get("known_missing_deps", [])
        }
        self.assertIn(("pig_chicken_spread", "chicken_spot"), known)
        self.assertIn(("pork_stock_signal", "pork_spot"), known)
        self.assertIn(("gold_etf_signal", "gold_etf"), known)
        self.assertNotIn(("term_structure", "pork_futures_far"), known)


if __name__ == "__main__":
    unittest.main()
