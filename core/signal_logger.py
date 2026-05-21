import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

SQLITE_TIMEOUT = 10


class SignalLogger:
    """信号落库：SQLite 记录每次因子信号，支持回溯复盘"""

    _instance = None

    def __new__(cls, db_path: str = "./data/signals.db"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db_path = Path(db_path)
            cls._instance._init_db()
        elif str(cls._instance._db_path) != str(Path(db_path)):
            logger.warning(
                f"SignalLogger 已用 db_path={cls._instance._db_path} 初始化，"
                f"忽略新参数 db_path={db_path}"
            )
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None

    def _ensure_columns(self, conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
        migrations = []
        if "run_id" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN run_id TEXT")
        if "signal_json" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN signal_json TEXT")
        if "factor_data_json" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN factor_data_json TEXT")
        if "trigger" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN trigger TEXT")
        if "holding_days" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN holding_days INTEGER")
        if "stop_loss" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN stop_loss REAL")
        if "as_of" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN as_of TEXT")
        if "signal_strength" not in columns:
            migrations.append("ALTER TABLE signals ADD COLUMN signal_strength REAL")
        for sql in migrations:
            conn.execute(sql)

    def _migrate_signal_runs(self, conn):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(signal_runs)")}
        if "run_id" not in columns:
            conn.execute("ALTER TABLE signal_runs ADD COLUMN run_id TEXT")
        if "as_of" not in columns:
            conn.execute("ALTER TABLE signal_runs ADD COLUMN as_of TEXT")

    def _init_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
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
            CREATE TABLE IF NOT EXISTS signal_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_name TEXT NOT NULL,
                has_signal INTEGER DEFAULT 0,
                run_date TEXT NOT NULL,
                UNIQUE(factor_name, run_date)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_factor ON signals(factor_name, created_at)
        """)
        self._ensure_columns(conn)
        self._migrate_signal_runs(conn)
        conn.commit()
        conn.close()

    def log(self, factor_name: str, signal: Optional[Dict[str, Any]],
            strength: Optional[float] = None, factor_data: Any = None,
            as_of: Optional[str] = None, run_id: Optional[str] = None):
        now = datetime.now()
        run_date = as_of or now.strftime("%Y-%m-%d")
        run_id = run_id or f"{factor_name}:{run_date}"
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
            conn.execute(
                """INSERT OR REPLACE INTO signal_runs (factor_name, has_signal, run_date, run_id, as_of)
                   VALUES (?, ?, ?, ?, ?)""",
                (factor_name, 1 if signal is not None else 0, run_date, run_id, as_of)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"运行记录落库失败 factor={factor_name}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if signal is None:
            return
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
            signal_json = json.dumps(signal, ensure_ascii=False, default=str)
            factor_data_json = json.dumps(factor_data, ensure_ascii=False, default=str) if factor_data is not None else None
            conn.execute(
                """INSERT INTO signals (
                       factor_name, direction, strength, confidence, reason, asset,
                       factor_data, created_at, run_id, signal_json, factor_data_json,
                       trigger, holding_days, stop_loss, as_of, signal_strength
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    factor_name,
                    signal.get("direction"),
                    strength if strength is not None else signal.get("strength"),
                    signal.get("confidence"),
                    signal.get("reason"),
                    signal.get("asset"),
                    factor_data_json,
                    now.isoformat(),
                    run_id,
                    signal_json,
                    factor_data_json,
                    signal.get("trigger"),
                    signal.get("holding_days"),
                    signal.get("stop_loss"),
                    as_of,
                    signal.get("signal_strength", signal.get("strength")),
                )
            )
            conn.commit()
        except Exception as e:
            logger.error(f"信号落库失败 factor={factor_name}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _select_columns(self, conn):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(signals)")]
        preferred = [
            "id", "factor_name", "direction", "strength", "signal_strength", "confidence",
            "reason", "asset", "trigger", "holding_days", "stop_loss", "run_id", "as_of",
            "signal_json", "factor_data_json", "factor_data", "created_at",
        ]
        seen = set(columns)
        return [col for col in preferred if col in seen]

    def query(self, factor_name: str = None, days: int = 30,
              limit: int = 100) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        conn.row_factory = sqlite3.Row
        selected = ", ".join(self._select_columns(conn))
        sql = f"SELECT {selected} FROM signals WHERE 1=1"
        params = []
        if factor_name:
            sql += " AND factor_name = ?"
            params.append(factor_name)
        if days:
            sql += " AND created_at >= date('now', ? || ' days')"
            params.append(f"-{days}")
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def stats(self, factor_name: str = None, days: int = 90) -> Dict[str, Any]:
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        conn.row_factory = sqlite3.Row
        where = ""
        params = []
        if factor_name:
            where = " AND factor_name = ?"
            params.append(factor_name)
        params.append(f"-{days}")

        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM signals WHERE 1=1{where} AND created_at >= date('now', ? || ' days')",
            params
        ).fetchone()["cnt"]

        buy = conn.execute(
            f"SELECT COUNT(*) as cnt FROM signals WHERE direction='BUY'{where} AND created_at >= date('now', ? || ' days')",
            params
        ).fetchone()["cnt"]

        sell = conn.execute(
            f"SELECT COUNT(*) as cnt FROM signals WHERE direction='SELL'{where} AND created_at >= date('now', ? || ' days')",
            params
        ).fetchone()["cnt"]

        by_factor = conn.execute(
            f"""SELECT factor_name, COUNT(*) as cnt, AVG(strength) as avg_strength
                FROM signals WHERE 1=1{where} AND created_at >= date('now', ? || ' days')
                GROUP BY factor_name ORDER BY cnt DESC""",
            params
        ).fetchall()

        conn.close()
        return {
            "total_signals": total,
            "buy_signals": buy,
            "sell_signals": sell,
            "by_factor": [dict(r) for r in by_factor],
            "period_days": days,
        }