from pathlib import Path
from typing import Any, Dict, Optional
import logging
import threading
import pandas as pd

from core.price_schema import is_price_like

logger = logging.getLogger(__name__)


class DataBus:
    """单例数据中心：统一加载+缓存，所有因子共享，避免重复 I/O

    Price column semantics for futures data (after roll-gap adjustment):

    - ``close_raw``: Original unadjusted close from the data source.
    - ``close_adj``: Close after roll-gap adjustment (shifts subsequent prices
      to remove discontinuities at contract roll dates).
    - ``close``: Backward-compatible alias for ``close_adj``.
    - ``return_raw``: Daily return computed from ``close_raw``.
    - ``return_adj``: Daily return computed from ``close_adj``.

    For non-futures price data (macro, FRED, etc.) where no roll-gap adjustment
    is applied, ``close_raw == close_adj == close`` and
    ``return_raw == return_adj``.

    Recommendation:
    - Use ``return_raw`` for P&L / backtest returns (tradeable reality).
    - Use ``close_adj`` / ``return_adj`` for valuation / z-score positioning
      (removes roll noise).
    """
    _instance: Optional["DataBus"] = None

    _CHINESE_FUTURES = {
        "pork_futures", "pork_futures_far", "egg_futures",
        "soybean_meal_futures", "corn_futures", "soybean_domestic_futures",
        "soybean_import_futures", "rapeseed_meal_futures", "soybean_oil_futures",
        "crude_oil_futures", "thermal_coal_futures",
        "copper_futures", "aluminum_futures", "rebar_futures",
        "gold_futures", "silver_futures", "iron_ore_futures",
    }

    def __new__(cls, data_dir: str = "./data"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data_dir = Path(data_dir)
            cls._instance._cache = {}
            cls._instance._lock = threading.Lock()
        elif str(cls._instance._data_dir) != str(Path(data_dir)):
            raise RuntimeError(
                f"DataBus 已用 data_dir={cls._instance._data_dir} 初始化，"
                f"不能切换为 data_dir={data_dir}。请先调用 DataBus.reset() 重置。"
            )
        return cls._instance

    @classmethod
    def reset(cls):
        if cls._instance is not None:
            cls._instance._cache.clear()
        cls._instance = None

    def get(self, name: str, date_col: str = 'date') -> Optional[pd.DataFrame]:
        if name in self._cache:
            return self._cache[name]
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            path = self._data_dir / f"{name}.parquet"
            if not path.exists():
                return None
            df = pd.read_parquet(path)
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.sort_values(date_col)
            adjusted = False
            if 'close' in df.columns and name in self._CHINESE_FUTURES:
                df = self._adjust_roll_gap(df)
                adjusted = True
            elif 'close' in df.columns and is_price_like(name):
                # Non-futures price data: explicit columns without adjustment
                df = df.copy()
                if 'close_raw' not in df.columns:
                    df['close_raw'] = df['close']
                if 'close_adj' not in df.columns:
                    df['close_adj'] = df['close']
                if 'return_raw' not in df.columns:
                    df['return_raw'] = df['close'].pct_change()
                if 'return_adj' not in df.columns:
                    df['return_adj'] = df['close'].pct_change()
            df = self._attach_metadata(df, name=name, path=path, adjusted=adjusted)
            self._cache[name] = df
            return df

    @staticmethod
    def _attach_metadata(df: pd.DataFrame, name: str, path: Path, adjusted: bool = False) -> pd.DataFrame:
        """Attach observational metadata without changing factor-facing columns."""
        result = df.copy()
        is_price = is_price_like(name) and 'date' in result.columns and 'close' in result.columns
        explicit_columns = sorted({'close_raw', 'close_adj', 'return_raw', 'return_adj'} & set(result.columns))
        metadata: Dict[str, Any] = {
            "dataset": name,
            "source_file": str(path),
            "rows": int(len(result)),
            "columns": list(result.columns),
            "is_price_data": bool(is_price),
        }
        if is_price:
            metadata.update({
                "price_mode": "explicit_price_columns" if explicit_columns else "legacy_close",
                "explicit_price_columns": explicit_columns,
                "adjustment": "roll_gap_adjusted" if adjusted else "raw",
            })
        if result.attrs.get("roll_gap_adjustment"):
            metadata["roll_gap_adjustment"] = result.attrs["roll_gap_adjustment"]
        result.attrs["data_bus"] = metadata
        return result

    @staticmethod
    def _adjust_roll_gap(df: pd.DataFrame) -> pd.DataFrame:
        close = df['close'].astype(float)
        daily_returns = close.pct_change()

        if len(daily_returns) >= 20:
            rolling_std = daily_returns.rolling(20, min_periods=10).std()
            is_roll_gap = daily_returns.abs() > (rolling_std * 5)
        else:
            threshold = abs(close.median()) * 0.08
            is_roll_gap = daily_returns.abs() > threshold

        adjusted = close.copy()
        cumulative_adj = 0.0
        roll_count = 0
        for i in range(1, len(close)):
            if is_roll_gap.iloc[i]:
                gap_amount = close.iloc[i] - adjusted.iloc[i - 1]
                cumulative_adj += gap_amount
                roll_count += 1
            adjusted.iloc[i] = close.iloc[i] - cumulative_adj

        if roll_count > 0:
            logger.info(
                f"换月跳空调整: 检测到 {roll_count} 次跳空, "
                f"累计调整 {cumulative_adj:.2f}, 数据量 {len(close)}"
            )

        df = df.copy()
        df['close_raw'] = close
        df['close_adj'] = adjusted
        df['close'] = adjusted  # backward-compatible default
        df['return_raw'] = close.pct_change()
        df['return_adj'] = adjusted.pct_change()
        df.attrs["roll_gap_adjustment"] = {
            "method": "pct_change_threshold",
            "roll_count": int(roll_count),
            "cumulative_adjustment": float(cumulative_adj),
        }
        return df

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        df = self.get(name)
        if df is None:
            return None
        metadata = df.attrs.get("data_bus")
        return dict(metadata) if metadata else None

    def invalidate(self, name: str = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def preload(self, names: list):
        for name in names:
            self.get(name)

    @property
    def cache_stats(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._cache.items()}