import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


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

    def _init_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
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
            CREATE INDEX IF NOT EXISTS idx_signals_factor ON signals(factor_name, created_at)
        """)
        conn.commit()
        conn.close()

    def log(self, factor_name: str, signal: Optional[Dict[str, Any]],
            strength: Optional[float] = None, factor_data: Any = None):
        if signal is None:
            return
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                """INSERT INTO signals (factor_name, direction, strength, confidence, reason, asset, factor_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    factor_name,
                    signal.get("direction"),
                    strength,
                    signal.get("confidence"),
                    signal.get("reason"),
                    signal.get("asset"),
                    json.dumps(factor_data, default=str) if factor_data else None,
                    datetime.now().isoformat()
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

    def query(self, factor_name: str = None, days: int = 30,
              limit: int = 100) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM signals WHERE 1=1"
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
        conn = sqlite3.connect(str(self._db_path))
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