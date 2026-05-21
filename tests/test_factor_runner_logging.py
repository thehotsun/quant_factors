import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_bus import DataBus
from core.factor_runner import FactorRunner


class CapturingSignalLogger:
    def __init__(self):
        self.calls = []

    def log(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class DummyICMonitor:
    def __init__(self):
        self.snapshots = []

    def snapshot(self, *args, **kwargs):
        self.snapshots.append((args, kwargs))


def _write_price(data_dir: str):
    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    df = pd.DataFrame({"date": dates, "close": [100.0 for _ in range(len(dates))]})
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    df.to_parquet(Path(data_dir) / "pork_futures.parquet", index=False)


class FactorRunnerLoggingTest(unittest.TestCase):
    def test_run_chain_passes_as_of_and_run_id_to_signal_logger(self):
        with tempfile.TemporaryDirectory() as tmp:
            DataBus.reset()
            _write_price(tmp)
            chains = {
                "momentum": {
                    "category": "technical",
                    "description": "动量",
                    "asset": "生猪期货",
                    "factor_module": "factors.technical.momentum",
                    "factor_class": "MomentumFactor",
                    "symbol": "pork_futures",
                    "data_deps": ["pork_futures"],
                }
            }
            logger = CapturingSignalLogger()
            runner = FactorRunner(chains, {}, tmp, logger, DummyICMonitor())

            result = runner.run_chain("momentum")

            self.assertIsNotNone(result)
            self.assertEqual(len(logger.calls), 1)
            args, kwargs = logger.calls[0]
            self.assertEqual(args[0], "momentum")
            self.assertRegex(kwargs["as_of"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(kwargs["run_id"], f"momentum:{kwargs['as_of']}")
            self.assertEqual(len(runner.ic_monitor.snapshots), 1)
            _, ic_kwargs = runner.ic_monitor.snapshots[0]
            self.assertEqual(ic_kwargs["snapshot_date"], kwargs["as_of"])


if __name__ == "__main__":
    unittest.main()
