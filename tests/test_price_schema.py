import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.price_schema import collect_price_dependencies, inspect_price_dependencies


class PriceSchemaTest(unittest.TestCase):
    def test_collect_price_dependencies(self):
        chains = {
            "momentum": {"data_deps": ["pork_futures", "cpi"]},
            "volatility_copper": {"data_deps": ["copper_futures"]},
            "macro": {"data_deps": ["cpi"]},
        }
        deps = collect_price_dependencies(chains)
        self.assertEqual(deps, ["copper_futures", "pork_futures"])

    def test_inspect_price_dependencies_reports_legacy_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [100.0]}).to_parquet(data_dir / "pork_futures.parquet", index=False)
            pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [200.0], "close_raw": [199.0]}).to_parquet(data_dir / "copper_futures.parquet", index=False)

            report = inspect_price_dependencies(data_dir, ["pork_futures", "copper_futures", "chicken_spot"])
            summary = report["summary"]
            self.assertEqual(summary["price_dependencies"], 3)
            self.assertEqual(summary["missing"], 1)
            self.assertEqual(summary["known_missing"], 1)
            self.assertEqual(summary["unexpected_missing"], 0)
            self.assertEqual(summary["invalid"], 0)
            self.assertEqual(summary["legacy_close"], 1)
            self.assertEqual(summary["explicit_price_columns"], 1)

            items = {item["name"]: item for item in report["items"]}
            self.assertEqual(items["pork_futures"]["schema"], "legacy_close")
            self.assertTrue(any("legacy date/close schema" in msg for msg in items["pork_futures"]["warnings"]))
            self.assertEqual(items["copper_futures"]["schema"], "explicit_price_columns")
            self.assertFalse(items["chicken_spot"]["exists"])
            self.assertEqual(items["chicken_spot"]["schema"], "known_missing")


if __name__ == "__main__":
    unittest.main()
