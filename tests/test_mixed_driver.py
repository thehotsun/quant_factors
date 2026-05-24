"""Tests for mixed signal factors and DataBus driver methods."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus
from core.chain_config import build_chain_definitions


class DataBusDriverMethodsTest(unittest.TestCase):
    def setUp(self):
        DataBus.reset()

    def tearDown(self):
        DataBus.reset()

    def test_get_price_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame({
                "date": pd.date_range("2024-01-01", periods=3),
                "close": [100.0, 101.0, 102.0],
            })
            df.to_parquet(Path(tmp) / "test.parquet", index=False)
            bus = DataBus(tmp)

            self.assertEqual(float(bus.get_price("test", "default").iloc[-1]), 102.0)
            self.assertEqual(float(bus.get_price("test", "raw").iloc[-1]), 102.0)
            self.assertEqual(float(bus.get_price("test", "adjusted").iloc[-1]), 102.0)
            self.assertIsNone(bus.get_price("missing", "default"))

    def test_get_price_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame({"date": ["2024-01-01"], "close": [1.0]}).to_parquet(
                Path(tmp) / "exists.parquet", index=False
            )
            bus = DataBus(tmp)
            with self.assertRaises(ValueError):
                bus.get_price("exists", "invalid_mode")

    def test_get_driver_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame({"date": ["2024-01-01"], "close": [1.0]}).to_parquet(
                Path(tmp) / "f1.parquet", index=False
            )
            bus = DataBus(tmp)

            chain_def = build_chain_definitions({
                "test": {
                    "drivers": {"futures": ["f1"], "spot": ["missing_spot"]},
                    "data_deps": ["f1"],
                }
            })["test"]

            bundle = bus.get_driver_bundle(chain_def)
            self.assertIn("futures", bundle)
            self.assertIn("spot", bundle)
            self.assertIsNotNone(bundle["futures"]["f1"])
            self.assertIsNone(bundle["spot"]["missing_spot"])

    def test_get_driver_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            bus = DataBus(tmp)
            chain_def = build_chain_definitions({
                "test": {
                    "drivers": {"futures": ["pork_futures"], "spot": ["chicken_spot"]},
                    "data_deps": ["pork_futures", "chicken_spot"],
                }
            })["test"]

            status = bus.get_driver_status(chain_def)
            self.assertEqual(status["futures"]["pork_futures"]["status"], "missing_unexpected")
            self.assertEqual(status["spot"]["chicken_spot"]["status"], "missing_known")


class MixedDriverFactorTest(unittest.TestCase):
    def test_mixed_driver_factor_base_properties(self):
        from factors.mixed.base import MixedDriverFactor

        class DummyFactor(MixedDriverFactor):
            def calculate(self):
                return {"factor_value": 0.5}
            def signal(self):
                return None

        DataBus.reset()
        with tempfile.TemporaryDirectory() as tmp:
            chain_def = build_chain_definitions({
                "test": {
                    "trade_asset": "TestETF(123456)",
                    "trade_asset_type": "etf",
                    "execution_asset": "123456",
                    "drivers": {"futures": ["f1"]},
                    "data_deps": ["f1"],
                }
            })["test"]

            factor = DummyFactor(data_dir=tmp, chain_def=chain_def)
            self.assertEqual(factor.trade_asset, "TestETF(123456)")
            self.assertEqual(factor.trade_asset_type, "etf")
            self.assertEqual(factor.execution_asset, "123456")
            self.assertEqual(factor.get_missing_drivers(), ["f1"])

    def test_make_signal_includes_metadata(self):
        from factors.mixed.base import MixedDriverFactor

        class DummyFactor(MixedDriverFactor):
            def calculate(self):
                return {"factor_value": 0.5}
            def signal(self):
                return self._make_signal(direction="BUY", reason="test")

        DataBus.reset()
        with tempfile.TemporaryDirectory() as tmp:
            chain_def = build_chain_definitions({
                "test": {
                    "trade_asset": "TestETF(123456)",
                    "trade_asset_type": "etf",
                    "execution_asset": "123456",
                    "drivers": {"futures": ["f1"]},
                    "data_deps": ["f1"],
                }
            })["test"]

            factor = DummyFactor(data_dir=tmp, chain_def=chain_def)
            factor._cached_data = {"factor_value": 0.5}
            sig = factor.signal()
            self.assertEqual(sig["trade_asset"], "TestETF(123456)")
            self.assertEqual(sig["execution_asset"], "123456")
            self.assertIn("drivers_used", sig)
            self.assertIn("missing_drivers", sig)


if __name__ == "__main__":
    unittest.main()
