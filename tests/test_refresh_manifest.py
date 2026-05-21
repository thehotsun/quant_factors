import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core.data_refresh import daily_data_refresh, first_valid_frame
from core.refresh_manifest import RefreshManifest


class DummyBus:
    def __init__(self):
        self.invalidated = False

    def invalidate(self):
        self.invalidated = True


class RefreshManifestTest(unittest.TestCase):
    def test_manifest_records_summary_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refresh_manifest.json"
            manifest = RefreshManifest(path, "daily_domestic")
            df = pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-01-02"]), "close": [1, 2]})
            manifest.record(name="test", filename="test.parquet", status="success", df=df, wrote=True)
            manifest.record(name="skip", filename="skip.parquet", status="skipped", df=None, wrote=False)
            payload = manifest.write()

            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["summary"]["total"], 2)
            self.assertEqual(saved["summary"]["success"], 1)
            self.assertEqual(saved["summary"]["skipped"], 1)
            self.assertEqual(saved["summary"]["written"], 1)
            self.assertEqual(saved["records"][0]["rows"], 2)
            self.assertEqual(saved["records"][0]["min_date"], "2024-01-01")
            self.assertEqual(saved["records"][0]["max_date"], "2024-01-02")
            self.assertEqual(payload["job"], "daily_domestic")

    def test_first_valid_frame_skips_none_and_empty_frames(self):
        valid = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [1.0]})
        result = first_valid_frame(lambda: None, lambda: pd.DataFrame(), lambda: valid)
        self.assertIs(result, valid)

    def test_daily_refresh_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "refresh_manifest.json"
            dummy_bus = DummyBus()
            sample = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [1.0]})

            def fake_save_parquet(df, name):
                return True

            def fake_tushare(*args, **kwargs):
                return sample

            def fake_pboc():
                return sample

            with patch("core.data_refresh.REFRESH_MANIFEST_PATH", manifest_path), \
                 patch("core.data_refresh.retry_fetch", side_effect=lambda name, fetcher, max_retries=3, base_delay=2: fetcher()), \
                 patch("download_history.save_parquet", side_effect=fake_save_parquet), \
                 patch("download_history.fetch_tushare_futures", side_effect=fake_tushare), \
                 patch("download_history.fetch_pboc_social_financing", side_effect=fake_pboc), \
                 patch("core.data_refresh.ak.macro_china_pmi", return_value=sample), \
                 patch("core.data_refresh.ak.macro_china_cpi", return_value=sample), \
                 patch("core.data_refresh.ak.macro_china_money_supply", return_value=sample):
                daily_data_refresh(dummy_bus)

            self.assertTrue(dummy_bus.invalidated)
            self.assertTrue(manifest_path.exists())
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["job"], "daily_domestic")
            self.assertEqual(saved["summary"]["failed"], 0)
            self.assertGreaterEqual(saved["summary"]["success"], 1)


if __name__ == "__main__":
    unittest.main()
