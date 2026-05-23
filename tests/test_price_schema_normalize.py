"""P1-1: 验证 normalize_price_frame 为价格数据添加显式列。"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.price_schema import normalize_price_frame, is_price_like, inspect_price_file


class TestNormalizePriceFrame(unittest.TestCase):
    def test_adds_explicit_columns(self):
        """价格 DataFrame 应被添加 close_raw/close_adj/return_raw/return_adj。"""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "close": [100.0, 101.0, 99.0],
        })
        result = normalize_price_frame(df, "pork_futures")
        self.assertIn("close_raw", result.columns)
        self.assertIn("close_adj", result.columns)
        self.assertIn("return_raw", result.columns)
        self.assertIn("return_adj", result.columns)
        # 非调整场景：raw == adj（值相同，列名不同）
        self.assertTrue((result["close_raw"] == result["close_adj"]).all())

    def test_returns_first_row_is_nan(self):
        """return 列第一行应为 NaN（pct_change 特性）。"""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "close": [100.0, 101.0],
        })
        result = normalize_price_frame(df, "corn_futures")
        self.assertTrue(pd.isna(result["return_raw"].iloc[0]))
        self.assertAlmostEqual(result["return_raw"].iloc[1], 0.01)

    def test_no_overwrite_existing_columns(self):
        """如果已有显式列，不覆盖。"""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "close": [100.0, 101.0],
            "close_raw": [99.0, 100.0],
        })
        result = normalize_price_frame(df, "pork_futures")
        # 不应覆盖已有的 close_raw
        self.assertEqual(result["close_raw"].iloc[0], 99.0)

    def test_non_price_data_unchanged(self):
        """非价格数据不处理。"""
        df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "value": [42.0]})
        result = normalize_price_frame(df, "cpi")
        self.assertNotIn("close_raw", result.columns)

    def test_empty_df_passthrough(self):
        """空 DataFrame 直接返回。"""
        df = pd.DataFrame()
        result = normalize_price_frame(df, "pork_futures")
        self.assertTrue(result.empty)

    def test_none_passthrough(self):
        """None 直接返回。"""
        result = normalize_price_frame(None, "pork_futures")
        self.assertIsNone(result)


class TestSaveParquetWithExplicitColumns(unittest.TestCase):
    """save_parquet 应为价格数据写入显式列。"""

    def test_price_file_has_explicit_columns(self):
        from download_history import save_parquet
        with tempfile.TemporaryDirectory() as tmp:
            import download_history
            old_dir = download_history.DATA_DIR
            try:
                download_history.DATA_DIR = Path(tmp)
                df = pd.DataFrame({
                    "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
                    "close": [100.0, 101.0, 99.0],
                })
                save_parquet(df, "pork_futures")
                saved = pd.read_parquet(Path(tmp) / "pork_futures.parquet")
                self.assertIn("close_raw", saved.columns)
                self.assertIn("close_adj", saved.columns)
                self.assertIn("return_raw", saved.columns)
                self.assertIn("return_adj", saved.columns)
            finally:
                download_history.DATA_DIR = old_dir

    def test_non_price_file_no_explicit_columns(self):
        from download_history import save_parquet
        with tempfile.TemporaryDirectory() as tmp:
            import download_history
            old_dir = download_history.DATA_DIR
            try:
                download_history.DATA_DIR = Path(tmp)
                df = pd.DataFrame({
                    "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                    "value": [1.0, 2.0],
                })
                save_parquet(df, "cpi")
                saved = pd.read_parquet(Path(tmp) / "cpi.parquet")
                self.assertNotIn("close_raw", saved.columns)
            finally:
                download_history.DATA_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
