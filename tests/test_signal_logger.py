import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.signal_logger import SignalLogger


class SignalLoggerContextTest(unittest.TestCase):
    def setUp(self):
        SignalLogger.reset_instance()

    def tearDown(self):
        SignalLogger.reset_instance()

    def test_log_persists_full_signal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signals.db"
            logger = SignalLogger(str(db_path))
            signal = {
                "direction": "BUY",
                "strength": 0.8,
                "signal_strength": 0.8,
                "confidence": 0.7,
                "reason": "test reason",
                "asset": "测试资产",
                "trigger": "test trigger",
                "holding_days": 10,
                "stop_loss": -0.03,
                "factor_value": 1.23,
                "meta": {"source": "unit-test"},
            }
            factor_data = {"factor_value": 1.23, "release_date": "2026-04-10"}

            logger.log("unit_factor", signal, strength=0.8, factor_data=factor_data, as_of="2026-04-15")
            rows = logger.query("unit_factor", days=None, limit=1)

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["run_id"], "unit_factor:2026-04-15")
            self.assertEqual(row["trigger"], "test trigger")
            self.assertEqual(row["holding_days"], 10)
            self.assertEqual(float(row["stop_loss"]), -0.03)
            self.assertEqual(float(row["signal_strength"]), 0.8)
            self.assertEqual(row["as_of"], "2026-04-15")

            self.assertEqual(row["signal_json"]["meta"]["source"], "unit-test")
            self.assertEqual(row["factor_data_json"]["release_date"], "2026-04-10")
            # Legacy column remains populated for old query/report consumers.
            self.assertEqual(row["factor_data"]["factor_value"], 1.23)

    def test_existing_database_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signals.db"
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_name TEXT NOT NULL,
                    direction TEXT,
                    strength REAL,
                    confidence REAL,
                    reason TEXT,
                    asset TEXT,
                    factor_data TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE signal_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_name TEXT NOT NULL,
                    has_signal INTEGER DEFAULT 0,
                    run_date TEXT NOT NULL,
                    UNIQUE(factor_name, run_date)
                )
            """)
            conn.commit()
            conn.close()

            SignalLogger(str(db_path))
            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
            conn.close()

            self.assertIn("run_id", columns)
            self.assertIn("signal_json", columns)
            self.assertIn("factor_data_json", columns)
            self.assertIn("trigger", columns)
            self.assertIn("holding_days", columns)
            self.assertIn("stop_loss", columns)
            self.assertIn("as_of", columns)

    def test_query_filters_and_decodes_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signals.db"
            logger = SignalLogger(str(db_path))
            logger.log(
                "unit_factor",
                {
                    "direction": "BUY",
                    "strength": 0.8,
                    "confidence": 0.7,
                    "reason": "matched",
                    "asset": "A",
                    "trigger": "t1",
                    "holding_days": 5,
                    "stop_loss": -0.02,
                },
                strength=0.8,
                factor_data={"factor_value": 1.0},
                as_of="2026-04-15",
                run_id="unit_factor:2026-04-15",
            )
            logger.log(
                "unit_factor",
                {
                    "direction": "SELL",
                    "strength": -0.5,
                    "confidence": 0.6,
                    "reason": "other",
                    "asset": "A",
                    "trigger": "t2",
                },
                strength=-0.5,
                factor_data={"factor_value": 2.0},
                as_of="2026-04-16",
                run_id="unit_factor:2026-04-16",
            )

            rows = logger.query(
                factor_name="unit_factor",
                days=None,
                as_of="2026-04-15",
                trigger="t1",
                direction="BUY",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "unit_factor:2026-04-15")
            self.assertEqual(rows[0]["signal_json"]["trigger"], "t1")
            self.assertEqual(rows[0]["factor_data_json"]["factor_value"], 1.0)

            stats = logger.stats(factor_name="unit_factor", days=None, trigger="t1")
            self.assertEqual(stats["total_signals"], 1)
            self.assertEqual(stats["buy_signals"], 1)
            self.assertEqual(stats["sell_signals"], 0)
            self.assertEqual(stats["by_trigger"][0]["trigger"], "t1")


if __name__ == "__main__":
    unittest.main()
