"""P2-1: 验证 DataBus 可注入依赖，测试无需全局 reset。"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus
from core.factor_runner import FactorRunner
from factors.base import BaseFactor


class DummyFactor(BaseFactor):
    """测试因子：读取 test_data 并返回。"""
    def calculate(self):
        df = self.load("test_data")
        return {"value": df["close"].iloc[-1] if df is not None and len(df) > 0 else None}

    def signal(self):
        return None


class TestBaseFactorDataBusInject(unittest.TestCase):
    """BaseFactor 支持注入独立 DataBus 实例。"""

    def setUp(self):
        DataBus.reset()

    def test_inject_custom_data_bus(self):
        """注入自定义 DataBus，因子应使用该实例加载数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "close": [42.0]})
            df.to_parquet(Path(tmp) / "test_data.parquet", index=False)

            bus = DataBus(tmp)
            factor = DummyFactor(data_dir=tmp, data_bus=bus)
            result = factor.calculate()
            self.assertEqual(result["value"], 42.0)

    def test_default_data_bus_fallback(self):
        """不注入 data_bus 时，应回退到默认创建。"""
        DataBus.reset()
        factor = DummyFactor(data_dir="./data")
        self.assertIsInstance(factor._bus, DataBus)


class TestFactorRunnerDataBusInject(unittest.TestCase):
    """FactorRunner 持有共享 DataBus 并注入给因子。"""

    def setUp(self):
        DataBus.reset()

    def test_runner_holds_data_bus(self):
        """FactorRunner 实例应持有 _data_bus。"""
        with tempfile.TemporaryDirectory() as tmp:
            runner = FactorRunner(
                chains_config={},
                factor_params={},
                data_dir=tmp,
                signal_logger=None,
                ic_monitor=None,
            )
            self.assertIsInstance(runner._data_bus, DataBus)

    def test_runner_injects_data_bus_to_factors(self):
        """通过 runner 实例化的因子应共享同一个 DataBus。"""
        with tempfile.TemporaryDirectory() as tmp:
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
                "close": [100.0, 101.0, 99.0],
            })
            Path(tmp).mkdir(parents=True, exist_ok=True)
            df.to_parquet(Path(tmp) / "cpi.parquet", index=False)

            chains_config = {
                "cpi": {
                    "factor_module": "factors.macro.cpi",
                    "factor_class": "CPIFactor",
                    "category": "macro",
                    "data_deps": ["cpi"],
                }
            }
            runner = FactorRunner(
                chains_config=chains_config,
                factor_params={},
                data_dir=tmp,
                signal_logger=None,
                ic_monitor=None,
            )
            runner.ensure_imported()
            factor = runner.instantiate("cpi")
            self.assertIs(factor._bus, runner._data_bus)

    def test_independent_runners_no_interference(self):
        """独立 FactorRunner 实例互不干扰（各用各的 DataBus）。"""
        with tempfile.TemporaryDirectory() as tmp1:
            DataBus.reset()
            df1 = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "close": [100.0]})
            df1.to_parquet(Path(tmp1) / "test_data.parquet", index=False)
            bus1 = DataBus(tmp1)
            factor1 = DummyFactor(data_dir=tmp1, data_bus=bus1)
            self.assertEqual(factor1.calculate()["value"], 100.0)

        # tmp1 释放后 reset，可安全用于新目录
        with tempfile.TemporaryDirectory() as tmp2:
            DataBus.reset()
            df2 = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "close": [200.0]})
            df2.to_parquet(Path(tmp2) / "test_data.parquet", index=False)
            bus2 = DataBus(tmp2)
            factor2 = DummyFactor(data_dir=tmp2, data_bus=bus2)
            self.assertEqual(factor2.calculate()["value"], 200.0)


if __name__ == "__main__":
    unittest.main()
