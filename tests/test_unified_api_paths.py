"""P0-1: 验证 /factor、/signal、/analyze 三条路径执行一致性。

三个 API 都应走 FactorRunner 统一方法，确保：
- /factor 调用 calculate_only（含 normalize_factor_data）
- /signal 调用 signal_only（含 calculate + signal + 日志）
- /analyze 调用 run_chain（含 calculate + signal + 日志 + IC snapshot）
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from core.data_bus import DataBus
from core.factor_runner import FactorRunner, normalize_factor_data


def _make_runner(tmp_dir):
    """创建最小可用的 FactorRunner 实例。"""
    chains_config = {
        "test_chain": {
            "factor_module": "factors.macro.cpi",
            "factor_class": "CPIFactor",
            "category": "macro",
            "description": "test",
            "data_deps": ["cpi"],
        }
    }
    signal_logger = MagicMock()
    ic_monitor = MagicMock()
    return FactorRunner(
        chains_config=chains_config,
        factor_params={},
        data_dir=tmp_dir,
        signal_logger=signal_logger,
        ic_monitor=ic_monitor,
    )


def _write_cpi(data_dir):
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"])
    df = pd.DataFrame({"date": dates, "全国-同比增长": [0.5, 0.8, 1.0, 1.2]})
    df.to_parquet(Path(data_dir) / "cpi.parquet", index=False)


class TestCalculateOnly(unittest.TestCase):
    """calculate_only 返回标准化 factor_data，不触发 signal/日志。"""

    def test_returns_normalized_factor_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            result = runner.calculate_only("test_chain")

            self.assertIsNotNone(result)
            self.assertIn("factor_data", result)
            self.assertIn("factor_value", result["factor_data"])
            self.assertNotIn("error", result)

    def test_returns_none_for_unknown_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            runner = _make_runner(tmp)
            runner.ensure_imported()

            result = runner.calculate_only("nonexistent")
            self.assertIsNone(result)

    def test_does_not_call_signal_logger(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            runner.calculate_only("test_chain")
            runner.signal_logger.log.assert_not_called()


class TestSignalOnly(unittest.TestCase):
    """signal_only 包含 calculate + signal + 日志，不触发 IC snapshot。"""

    def test_returns_signal_and_factor_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            result = runner.signal_only("test_chain")

            self.assertIsNotNone(result)
            self.assertIn("factor_data", result)
            self.assertIn("signal", result)
            self.assertIn("signal_strength", result)
            self.assertNotIn("error", result)

    def test_calls_signal_logger(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            runner.signal_only("test_chain")
            runner.signal_logger.log.assert_called_once()

    def test_does_not_call_ic_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            runner.signal_only("test_chain")
            runner.ic_monitor.snapshot.assert_not_called()

    def test_returns_none_for_unknown_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            runner = _make_runner(tmp)
            runner.ensure_imported()

            result = runner.signal_only("nonexistent")
            self.assertIsNone(result)


class TestRunChain(unittest.TestCase):
    """run_chain 是完整链路：calculate + signal + 日志 + IC snapshot。"""

    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            result = runner.run_chain("test_chain")

            self.assertIsNotNone(result)
            self.assertIn("factor_data", result)
            self.assertIn("opportunity", result)
            self.assertIn("signal_strength", result)
            # signal_logger 和 ic_monitor 都应被调用
            runner.signal_logger.log.assert_called_once()
            runner.ic_monitor.snapshot.assert_called_once()


class TestApiConsistency(unittest.TestCase):
    """三条路径的 factor_data 应包含相同的标准化字段。"""

    def test_factor_value_present_in_all_paths(self):
        """calculate_only、signal_only、run_chain 都应返回含 factor_value 的 factor_data。"""
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_cpi(tmp)
            runner = _make_runner(tmp)
            runner.ensure_imported()

            calc = runner.calculate_only("test_chain")
            sig = runner.signal_only("test_chain")
            full = runner.run_chain("test_chain")

            for result, path in [(calc, "calculate_only"), (sig, "signal_only"), (full, "run_chain")]:
                with self.subTest(path=path):
                    self.assertIsNotNone(result)
                    fd = result["factor_data"]
                    self.assertIsNotNone(fd)
                    self.assertIn("factor_value", fd, f"{path} 缺少 factor_value")


if __name__ == "__main__":
    unittest.main()
