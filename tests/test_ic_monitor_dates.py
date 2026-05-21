import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from evaluation.ic_monitor import ICMonitor


class ICMonitorDateAuditTest(unittest.TestCase):
    def tearDown(self):
        ICMonitor._instance = None

    def test_snapshot_accepts_explicit_snapshot_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ic.db"
            monitor = ICMonitor(str(db_path))
            monitor.snapshot("factor_a", 1.23, 0.5, snapshot_date="2024-03-15")

            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT factor_name, factor_value, signal_strength, snapshot_date FROM factor_snapshots").fetchone()
            conn.close()
            self.assertEqual(row, ("factor_a", 1.23, 0.5, "2024-03-15"))

    def test_compute_ic_returns_date_audit_without_changing_result_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ic.db"
            monitor = ICMonitor(str(db_path))
            dates = pd.date_range("2024-01-01", periods=40, freq="D")
            for i, d in enumerate(dates[:30]):
                monitor.snapshot("factor_a", float(i), snapshot_date=d.strftime("%Y-%m-%d"))

            price_df = pd.DataFrame({
                "date": dates,
                "close": [100.0 + i for i in range(len(dates))],
            })
            result = monitor.compute_ic("factor_a", price_df, forward_days=5, window=20)

            self.assertIsNotNone(result)
            self.assertIn("ic", result)
            self.assertEqual(result["forward_days"], 5)
            audit = result["date_audit"]
            self.assertEqual(audit["snapshot_start"], "2024-01-11")
            self.assertEqual(audit["snapshot_end"], "2024-01-30")
            self.assertEqual(audit["forward_return_start"], "2024-01-16")
            self.assertEqual(audit["forward_return_end"], "2024-02-04")
            self.assertEqual(audit["price_start"], "2024-01-01")
            self.assertEqual(audit["price_end"], "2024-02-09")
            self.assertEqual(audit["price_col"], "close")
            self.assertEqual(audit["forward_dates_available"], 20)


if __name__ == "__main__":
    unittest.main()
