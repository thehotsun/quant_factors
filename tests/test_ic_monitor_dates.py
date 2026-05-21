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
            dates = pd.to_datetime([
                "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
                "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12",
                "2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19",
                "2024-01-22", "2024-01-23", "2024-01-24", "2024-01-25", "2024-01-26",
                "2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02",
                "2024-02-05", "2024-02-06", "2024-02-07", "2024-02-08", "2024-02-09",
                "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16",
                "2024-02-19", "2024-02-20", "2024-02-21", "2024-02-22", "2024-02-23",
            ])
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
            self.assertEqual(audit["snapshot_start"], "2024-01-15")
            self.assertEqual(audit["snapshot_end"], "2024-02-09")
            self.assertEqual(audit["forward_return_start"], "2024-01-22")
            self.assertEqual(audit["forward_return_end"], "2024-02-16")
            self.assertEqual(audit["forward_date_mode"], "price_index_offset")
            self.assertEqual(audit["price_start"], "2024-01-01")
            self.assertEqual(audit["price_end"], "2024-02-23")
            self.assertEqual(audit["price_col"], "close")
            self.assertEqual(audit["forward_dates_available"], 20)


if __name__ == "__main__":
    unittest.main()
