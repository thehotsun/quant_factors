"""Tests for DataBus explicit price columns (A1-5)."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus


class ExplicitPriceColumnsTest(unittest.TestCase):
    def setUp(self):
        DataBus.reset()
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)

    def tearDown(self):
        DataBus.reset()

    def _write_parquet(self, name, df):
        df.to_parquet(self.data_dir / f"{name}.parquet", index=False)

    def test_futures_gets_explicit_columns(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "close": [100.0, 102.0, 101.0],
        })
        self._write_parquet("pork_futures", df)
        bus = DataBus(str(self.data_dir))
        result = bus.get("pork_futures")
        self.assertIn("close_raw", result.columns)
        self.assertIn("close_adj", result.columns)
        self.assertIn("return_raw", result.columns)
        self.assertIn("return_adj", result.columns)
        # close should equal close_adj (the adjusted version)
        pd.testing.assert_series_equal(result["close"], result["close_adj"], check_names=False)

    def test_non_futures_price_gets_explicit_columns(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "close": [200.0, 210.0, 205.0],
        })
        self._write_parquet("brent_oil", df)
        bus = DataBus(str(self.data_dir))
        result = bus.get("brent_oil")
        self.assertIn("close_raw", result.columns)
        self.assertIn("close_adj", result.columns)
        self.assertIn("return_raw", result.columns)
        self.assertIn("return_adj", result.columns)
        # Non-futures: raw == adj
        pd.testing.assert_series_equal(result["close_raw"], result["close_adj"], check_names=False)

    def test_metadata_tracks_price_mode(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "close": [100.0, 102.0],
        })
        self._write_parquet("copper_futures", df)
        bus = DataBus(str(self.data_dir))
        bus.get("copper_futures")
        meta = bus.get_metadata("copper_futures")
        self.assertEqual(meta["price_mode"], "explicit_price_columns")
        self.assertIn("close_raw", meta["explicit_price_columns"])
        self.assertIn("close_adj", meta["explicit_price_columns"])

    def test_non_price_data_unchanged(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "value": [42.0]})
        self._write_parquet("pmi", df)
        bus = DataBus(str(self.data_dir))
        result = bus.get("pmi")
        self.assertNotIn("close_raw", result.columns)
        self.assertNotIn("close_adj", result.columns)


if __name__ == "__main__":
    unittest.main()
