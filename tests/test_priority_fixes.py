import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus
from core.factor_runner import normalize_factor_data
from core.macro_calendar import available_asof
from factors.base import BaseFactor
from factors.macro.cpi import CPIFactor
from factors.macro.money_supply import MoneySupplyFactor
from factors.macro.pmi import PMIFactor
from factors.macro.social_financing import SocialFinancingFactor


class DummyFactor(BaseFactor):
    def calculate(self):
        return {}


def _write(df, data_dir, name):
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    df.to_parquet(Path(data_dir) / f"{name}.parquet", index=False)


class PriorityFixesTest(unittest.TestCase):
    def test_make_signal_has_stable_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            factor = DummyFactor(data_dir=tmp)
            signal = factor._make_signal(
                asset="X", direction="BUY", reason="reason",
                strength=2.5, confidence=1.5, trigger="t", custom=123,
            )
            self.assertEqual(signal["strength"], 1.0)
            self.assertEqual(signal["signal_strength"], 1.0)
            self.assertEqual(signal["confidence"], 1.0)
            self.assertEqual(signal["trigger"], "t")
            self.assertEqual(signal["meta"]["custom"], 123)

    def test_factor_data_normalization_adds_factor_value(self):
        data = normalize_factor_data({"current_cpi": 1.2}, "cpi")
        self.assertEqual(data["factor_value"], 1.2)

    def test_macro_asof_filters_unreleased_rows(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-03-01", "2026-04-01"]), "value": [1.0, 2.0]})
        visible = available_asof(df, "cpi", "2026-04-15")
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible.iloc[-1]["value"], 1.0)

    def test_macro_factors_emit_factor_value_and_release_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            dates = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"])
            _write(pd.DataFrame({"date": dates, "全国-同比增长": [0.5, 0.8, 1.0, 1.2]}), tmp, "cpi")
            _write(pd.DataFrame({"date": dates, "制造业-指数": [49.0, 49.5, 50.1, 50.4]}), tmp, "pmi")
            _write(pd.DataFrame({"date": dates, "货币和准货币(M2)-同比增长": [8.0, 8.2, 8.5, 8.6]}), tmp, "m2")
            _write(pd.DataFrame({"date": dates, "社会融资规模增量": [10000, 12000, 15000, 16000]}), tmp, "social_financing")

            for cls in [CPIFactor, PMIFactor, MoneySupplyFactor, SocialFinancingFactor]:
                with self.subTest(cls=cls.__name__):
                    DataBus.reset()
                    data = cls(data_dir=tmp).calculate()
                    self.assertIn("factor_value", data)
                    self.assertIn("release_date", data)
                    self.assertIsNotNone(data["release_date"])


if __name__ == "__main__":
    unittest.main()
