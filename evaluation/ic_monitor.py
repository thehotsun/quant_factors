import sqlite3
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from scipy import stats

logger = logging.getLogger(__name__)


class ICMonitor:
    """IC 监控：跟踪因子预测能力衰减，发现失效因子"""

    _instance = None

    def __new__(cls, db_path: str = "./data/ic_monitor.db"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db_path = Path(db_path)
            cls._instance._initialized = False
        elif str(cls._instance._db_path) != str(Path(db_path)):
            logger.warning(
                f"ICMonitor 已用 db_path={cls._instance._db_path} 初始化，"
                f"忽略新参数 db_path={db_path}"
            )
        return cls._instance

    def __init__(self, db_path: str = "./data/ic_monitor.db"):
        if self._initialized:
            return
        self._initialized = True
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS factor_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_name TEXT NOT NULL,
                factor_value REAL,
                signal_strength REAL,
                snapshot_date TEXT NOT NULL,
                UNIQUE(factor_name, snapshot_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ic_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_name TEXT NOT NULL,
                ic_value REAL,
                ic_window INTEGER,
                computed_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_factor ON factor_snapshots(factor_name, snapshot_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ic_factor ON ic_records(factor_name, computed_at)")
        conn.commit()
        conn.close()

    def snapshot(self, factor_name: str, factor_value: float,
                 signal_strength: Optional[float] = None):
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                """INSERT OR REPLACE INTO factor_snapshots (factor_name, factor_value, signal_strength, snapshot_date)
                   VALUES (?, ?, ?, ?)""",
                (factor_name, factor_value, signal_strength, today)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"IC快照落库失败 factor={factor_name}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def compute_ic(self, factor_name: str, price_df: pd.DataFrame,
                   forward_days: int = 5, window: int = 60) -> Optional[Dict[str, Any]]:
        """计算因子 IC（Rank IC，即 Spearman 相关系数）"""
        conn = sqlite3.connect(str(self._db_path))
        snapshots = pd.read_sql_query(
            "SELECT snapshot_date, factor_value FROM factor_snapshots WHERE factor_name = ? ORDER BY snapshot_date",
            conn, params=(factor_name,)
        )
        conn.close()

        if snapshots.empty or len(snapshots) < 20:
            return None

        snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
        snapshots = snapshots.set_index("snapshot_date")

        if "date" in price_df.columns:
            price_df = price_df.copy()
            price_df["date"] = pd.to_datetime(price_df["date"])
            price_df = price_df.set_index("date")

        price_col = "close" if "close" in price_df.columns else price_df.columns[0]
        prices = price_df[price_col].astype(float)

        forward_returns = prices.pct_change(forward_days).shift(-forward_days)

        common_dates = snapshots.index.intersection(forward_returns.dropna().index)
        if len(common_dates) < 10:
            return None

        common_dates = common_dates[-window:] if len(common_dates) > window else common_dates

        fv = snapshots.loc[common_dates, "factor_value"]
        fr = forward_returns.loc[common_dates]

        valid = fv.notna() & fr.notna()
        fv = fv[valid]
        fr = fr[valid]

        if len(fv) < 10:
            return None

        ic, p_value = stats.spearmanr(fv, fr)
        ic = float(ic)
        p_value = float(p_value)

        self._save_ic(factor_name, ic, window)

        return {
            "factor_name": factor_name,
            "ic": round(ic, 4),
            "ic_abs": round(abs(ic), 4),
            "p_value": round(p_value, 4),
            "significant": p_value < 0.05,
            "sample_size": len(fv),
            "forward_days": forward_days,
            "window": window,
            "status": self._ic_status(ic),
        }

    def _ic_status(self, ic: float) -> str:
        abs_ic = abs(ic)
        if abs_ic >= 0.05:
            return "healthy"
        elif abs_ic >= 0.02:
            return "warning"
        else:
            return "decayed"

    def _save_ic(self, factor_name: str, ic: float, window: int):
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            "INSERT INTO ic_records (factor_name, ic_value, ic_window, computed_at) VALUES (?, ?, ?, ?)",
            (factor_name, ic, window, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_ic_history(self, factor_name: str, days: int = 90) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM ic_records WHERE factor_name = ?
               AND computed_at >= ? ORDER BY computed_at DESC""",
            (factor_name, (datetime.now() - timedelta(days=days)).isoformat())
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_decay_status(self, factor_name: str) -> Optional[Dict[str, Any]]:
        """获取因子衰减状态：对比近期 IC vs 历史 IC"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row

        recent = conn.execute(
            """SELECT AVG(ic_value) as avg_ic, COUNT(*) as cnt
               FROM ic_records WHERE factor_name = ?
               AND computed_at >= ?""",
            (factor_name, (datetime.now() - timedelta(days=30)).isoformat())
        ).fetchone()

        historical = conn.execute(
            """SELECT AVG(ic_value) as avg_ic, COUNT(*) as cnt
               FROM ic_records WHERE factor_name = ?""",
            (factor_name,)
        ).fetchone()
        conn.close()

        if not recent["cnt"]:
            return None

        recent_ic = recent["avg_ic"] or 0
        hist_ic = historical["avg_ic"] or 0

        decay_ratio = recent_ic / hist_ic if hist_ic != 0 else 1.0

        if decay_ratio < 0.3:
            trend = "severe_decay"
        elif decay_ratio < 0.6:
            trend = "moderate_decay"
        elif decay_ratio < 0.9:
            trend = "mild_decay"
        else:
            trend = "stable"

        return {
            "factor_name": factor_name,
            "recent_ic_avg": round(recent_ic, 4),
            "historical_ic_avg": round(hist_ic, 4),
            "decay_ratio": round(decay_ratio, 2),
            "trend": trend,
            "recent_samples": recent["cnt"],
            "total_samples": historical["cnt"],
        }

    def health_report(self) -> List[Dict[str, Any]]:
        """全因子健康报告"""
        conn = sqlite3.connect(str(self._db_path))
        rows = conn.execute(
            "SELECT DISTINCT factor_name FROM ic_records ORDER BY factor_name"
        ).fetchall()
        conn.close()

        report = []
        for (factor_name,) in rows:
            status = self.get_decay_status(factor_name)
            if status:
                report.append(status)
        return report