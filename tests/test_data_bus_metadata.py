import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus


def _write(df, data_dir, name):
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    df.to_parquet(Path(data_dir) / f"{name}.parquet", index=False)


class DataBusMetadataTest(unittest.TestCase):
    def setUp(self):
        DataBus.reset()

    def tearDown(self):
        DataBus.reset()

    def test_attaches_observational_metadata_without_extra_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame({"date": ["2024-01-02", "2024-01-01"], "close": [101.0, 100.0]})
            _write(df, tmp, "brent_oil")

            bus = DataBus(tmp)
            result = bus.get("brent_oil")
            self.assertEqual(list(result.columns), ["date", "close"])
            self.assertEqual(result["date"].dt.strftime("%Y-%m-%d").tolist(), ["2024-01-01", "2024-01-02"])

            meta = bus.get_metadata("brent_oil")
            self.assertEqual(meta["dataset"], "brent_oil")
            self.assertTrue(meta["is_price_data"])
            self.assertEqual(meta["price_mode"], "legacy_close")
            self.assertEqual(meta["adjustment"], "raw")
            self.assertEqual(meta["rows"], 2)
            self.assertTrue(meta["source_file"].endswith("brent_oil.parquet"))

    def test_chinese_futures_metadata_records_roll_adjustment(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame({
                "date": pd.date_range("2024-01-01", periods=10, freq="D"),
                "close": [0.1] * 5 + [1.0, 1.1, 1.2, 1.3, 1.4],
            })
            _write(df, tmp, "pork_futures")

            bus = DataBus(tmp)
            result = bus.get("pork_futures")
            self.assertIn("close_raw", result.columns)
            self.assertIn("close", result.columns)

            meta = bus.get_metadata("pork_futures")
            self.assertEqual(meta["adjustment"], "roll_gap_adjusted")
            self.assertEqual(meta["price_mode"], "explicit_price_columns")
            self.assertIn("close_raw", meta["explicit_price_columns"])
            self.assertGreaterEqual(meta["roll_gap_adjustment"]["roll_count"], 1)

    def test_get_metadata_returns_none_for_missing_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            self.assertIsNone(bus.get_metadata("missing"))


if __name__ == "__main__":
    unittest.main()
