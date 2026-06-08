import sqlite3
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from scipy import stats

logger = logging.getLogger(__name__)

SQLITE_TIMEOUT = 10


class ICMonitor:
    """IC 监控：跟踪因子预测能力衰减，发现失效因子"""

    _instance = None

    def __new__(cls, db_path: str = "./data/ic_monitor.db"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db_path = Path(db_path)
            cls._instance._initialized = False
        elif str(cls._instance._db_path) != str(Path(db_path)):
            raise RuntimeError(
                f"ICMonitor 已用 db_path={cls._instance._db_path} 初始化，"
                f"不能切换为 db_path={db_path}。请先调用 ICMonitor.reset() 重置。"
            )
        return cls._instance

    def __init__(self, db_path: str = "./data/ic_monitor.db"):
        if self._initialized:
            return
        self._initialized = True
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
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
                 signal_strength: Optional[float] = None,
                 snapshot_date: Optional[str] = None):
        today = snapshot_date or datetime.now().strftime("%Y-%m-%d")
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
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
                   forward_days: int = 5, window: int = 60,
                   price_mode: str = "adjusted") -> Optional[Dict[str, Any]]:
        """计算因子 IC（Rank IC，即 Spearman 相关系数）

        Args:
            price_mode: "adjusted" (default, use close_adj) or "raw" (use close_raw for P&L)
        """
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
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

        # P1-2: Support both adjusted and raw price for IC calculation
        if price_mode == "raw" and "close_raw" in price_df.columns:
            price_col = "close_raw"
        elif "close_adj" in price_df.columns:
            price_col = "close_adj"
        elif "close" in price_df.columns:
            price_col = "close"
        else:
            price_col = price_df.columns[0]
        prices = price_df[price_col].astype(float).sort_index()

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

        sample_dates = list(fv.index)
        price_index = pd.Index(prices.index)
        forward_end_dates = self._forward_end_dates(sample_dates, price_index, forward_days)
        available_forward_end_dates = [d for d in forward_end_dates if d is not None]

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
            "date_audit": {
                "snapshot_start": sample_dates[0].strftime("%Y-%m-%d"),
                "snapshot_end": sample_dates[-1].strftime("%Y-%m-%d"),
                "forward_return_start": available_forward_end_dates[0].strftime("%Y-%m-%d") if available_forward_end_dates else None,
                "forward_return_end": available_forward_end_dates[-1].strftime("%Y-%m-%d") if available_forward_end_dates else None,
                "forward_date_mode": "price_index_offset",
                "price_start": prices.index.min().strftime("%Y-%m-%d") if hasattr(prices.index.min(), "strftime") else str(prices.index.min()),
                "price_end": prices.index.max().strftime("%Y-%m-%d") if hasattr(prices.index.max(), "strftime") else str(prices.index.max()),
                "price_col": price_col,
                "forward_dates_available": len(available_forward_end_dates),
            },
            "status": self._ic_status(ic, p_value, len(fv)),
        }

    @staticmethod
    def _forward_end_dates(sample_dates: List[pd.Timestamp], price_index: pd.Index,
                           forward_days: int) -> List[Optional[pd.Timestamp]]:
        """Map each sample date to the Nth future observation in price_index.

        The IC return series uses ``pct_change(forward_days).shift(-forward_days)``,
        which is an observation offset rather than calendar-day arithmetic.  This
        helper exposes the same date boundary explicitly for audits.
        """
        sorted_index = pd.Index(pd.to_datetime(price_index)).sort_values()
        result: List[Optional[pd.Timestamp]] = []
        for date in sample_dates:
            ts = pd.to_datetime(date)
            if ts not in sorted_index:
                result.append(None)
                continue
            pos = sorted_index.get_loc(ts)
            if isinstance(pos, slice):
                pos = pos.start
            elif not isinstance(pos, (int, np.integer)):
                positions = list(pos)
                pos = positions[0] if positions else None
            if pos is None or pos + forward_days >= len(sorted_index):
                result.append(None)
            else:
                result.append(sorted_index[pos + forward_days])
        return result

    def _ic_status(self, ic: float, p_value: float = None, sample_size: int = None) -> str:
        """IC status with statistical significance check (P1-3).

        Uses p-value when available; falls back to absolute IC thresholds
        adjusted for sample size.
        """
        abs_ic = abs(ic)
        if p_value is not None:
            # Use statistical significance as primary signal
            if p_value < 0.01 and abs_ic >= 0.03:
                return "healthy"
            elif p_value < 0.05 and abs_ic >= 0.02:
                return "healthy"
            elif p_value < 0.10:
                return "warning"
            else:
                return "decayed"
        # Fallback: adjust threshold by sample size
        if sample_size and sample_size < 30:
            # Small sample: require higher IC
            if abs_ic >= 0.15:
                return "healthy"
            elif abs_ic >= 0.08:
                return "warning"
            else:
                return "decayed"
        # Default thresholds (N >= 30)
        if abs_ic >= 0.05:
            return "healthy"
        elif abs_ic >= 0.02:
            return "warning"
        else:
            return "decayed"

    def _save_ic(self, factor_name: str, ic: float, window: int):
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        conn.execute(
            "INSERT INTO ic_records (factor_name, ic_value, ic_window, computed_at) VALUES (?, ?, ?, ?)",
            (factor_name, ic, window, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_ic_history(self, factor_name: str, days: int = 90) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
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
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        conn.row_factory = sqlite3.Row

        recent = conn.execute(
            """SELECT AVG(ic_value) as avg_ic, COUNT(*) as cnt
               FROM ic_records WHERE factor_name = ?
               AND computed_at >= ?""",
            (factor_name, (datetime.now() - timedelta(days=30)).isoformat())
        ).fetchone()

        historical = conn.execute(
            """SELECT AVG(ic_value) as avg_ic, COUNT(*) as cnt
               FROM ic_records WHERE factor_name = ?
               AND computed_at < ?""",
            (factor_name, (datetime.now() - timedelta(days=30)).isoformat())
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

    # ── Direction hit rate ────────────────────────────────────────────────

    def compute_direction_hit_rate(self, factor_name: str, price_df: pd.DataFrame,
                                    forward_days: int = 5, window: int = 60) -> Optional[Dict[str, Any]]:
        """Compute direction hit rate: how often factor direction matches actual price move.

        For each snapshot, check if factor_value > 0 → price went up, or vice versa.
        Returns hit rate, sample size, and per-direction breakdown.
        """
        conn = sqlite3.connect(str(self._db_path), timeout=SQLITE_TIMEOUT)
        snapshots = pd.read_sql_query(
            "SELECT snapshot_date, factor_value FROM factor_snapshots WHERE factor_name = ? ORDER BY snapshot_date",
            conn, params=(factor_name,)
        )
        conn.close()

        if snapshots.empty or len(snapshots) < 10:
            return None

        snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
        snapshots = snapshots.set_index("snapshot_date")

        if "date" in price_df.columns:
            price_df = price_df.copy()
            price_df["date"] = pd.to_datetime(price_df["date"])
            price_df = price_df.set_index("date")

        price_col = "close" if "close" in price_df.columns else price_df.columns[0]
        prices = price_df[price_col].astype(float).sort_index()
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

        # Direction agreement: factor_value sign matches return sign
        factor_direction = np.sign(fv)
        actual_direction = np.sign(fr)
        hits = (factor_direction == actual_direction).sum()
        total = len(fv)

        # Per-direction breakdown
        positive_mask = factor_direction > 0
        negative_mask = factor_direction < 0

        positive_hits = ((factor_direction > 0) & (actual_direction > 0)).sum()
        positive_total = positive_mask.sum()
        negative_hits = ((factor_direction < 0) & (actual_direction < 0)).sum()
        negative_total = negative_mask.sum()

        return {
            "factor_name": factor_name,
            "method": "direction_hit_rate",
            "hit_rate": round(float(hits / total), 4),
            "sample_size": total,
            "forward_days": forward_days,
            "buy_hit_rate": round(float(positive_hits / positive_total), 4) if positive_total > 0 else None,
            "buy_samples": int(positive_total),
            "sell_hit_rate": round(float(negative_hits / negative_total), 4) if negative_total > 0 else None,
            "sell_samples": int(negative_total),
            "status": "healthy" if hits / total > 0.55 else ("warning" if hits / total > 0.50 else "decayed"),
        }

    def evaluate_factor(self, factor_name: str, price_df: pd.DataFrame,
                        factor_type: str = "time_series",
                        forward_days: int = 5, window: int = 60) -> Dict[str, Any]:
        """Unified factor evaluation that dispatches by factor type.

        factor_type: 'time_series' | 'trigger' | 'cross_sectional'
        Returns the appropriate evaluation result for the factor type.
        """
        if factor_type == "trigger":
            # For trigger-based factors, use direction hit rate
            result = self.compute_direction_hit_rate(
                factor_name, price_df, forward_days=forward_days, window=window
            )
            if result is None:
                return {"factor_name": factor_name, "method": "trigger", "error": "insufficient data"}
            return result

        if factor_type == "cross_sectional":
            # Cross-sectional IC not yet supported (single-asset system)
            return {
                "factor_name": factor_name,
                "method": "cross_sectional",
                "error": "not supported in single-asset system",
            }

        # Default: time-series IC (Rank IC)
        ic_result = self.compute_ic(factor_name, price_df, forward_days=forward_days, window=window)
        if ic_result is None:
            return {"factor_name": factor_name, "method": "time_series_ic", "error": "insufficient data"}

        # Also compute direction hit rate as supplementary info
        dir_result = self.compute_direction_hit_rate(
            factor_name, price_df, forward_days=forward_days, window=window
        )
        if dir_result:
            ic_result["direction_hit_rate"] = dir_result["hit_rate"]
            ic_result["direction_status"] = dir_result["status"]

        return ic_result