from pathlib import Path
from typing import Any, Dict, Optional
import logging
import threading
import pandas as pd

from core.price_schema import get_data_kind, is_price_like

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
        data_kind = get_data_kind(name)
        is_price = is_price_like(name) and 'date' in result.columns and 'close' in result.columns
        explicit_columns = sorted({'close_raw', 'close_adj', 'return_raw', 'return_adj'} & set(result.columns))
        metadata: Dict[str, Any] = {
            "dataset": name,
            "source_file": str(path),
            "rows": int(len(result)),
            "columns": list(result.columns),
            "is_price_data": bool(is_price),
            "data_kind": data_kind,
        }
        if is_price:
            metadata.update({
                "price_mode": "explicit_price_columns" if explicit_columns else "legacy_close",
                "explicit_price_columns": explicit_columns,
                "adjustment": "roll_gap_adjusted" if adjusted else "raw",
                "price_role": data_kind,
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

    def get_price(self, name: str, mode: str = "default") -> Optional[pd.Series]:
        """Get a specific price column by mode.

        Modes:
        - default: backward-compatible close (= close_adj)
        - raw: close_raw (original unadjusted)
        - adjusted: close_adj (roll-gap adjusted for futures, = raw for spot/equity)
        - return_raw: daily return from close_raw
        - return_adj: daily return from close_adj
        """
        df = self.get(name)
        if df is None:
            return None
        mode_map = {
            "default": "close",
            "raw": "close_raw",
            "adjusted": "close_adj",
            "return_raw": "return_raw",
            "return_adj": "return_adj",
        }
        col = mode_map.get(mode)
        if col is None:
            raise ValueError(f"Invalid price mode '{mode}'. Allowed: {list(mode_map.keys())}")
        if col not in df.columns:
            # Fallback: default/raw/adjusted all point to close if explicit columns missing
            if mode in ("default", "raw", "adjusted") and "close" in df.columns:
                return df["close"]
            return None
        return df[col]

    def get_driver_bundle(self, chain_def) -> Dict[str, Dict[str, Optional[pd.DataFrame]]]:
        """Load all driver datasets for a chain, grouped by type.

        Returns:
            {"futures": {"pork_futures": df, ...}, "spot": {...}, ...}
        Missing datasets are included as None.
        """
        drivers = getattr(chain_def, "drivers", {}) or {}
        bundle: Dict[str, Dict[str, Optional[pd.DataFrame]]] = {}
        for group, deps in drivers.items():
            group_data: Dict[str, Optional[pd.DataFrame]] = {}
            for dep_name in (deps if isinstance(deps, list) else []):
                group_data[dep_name] = self.get(dep_name)
            bundle[group] = group_data
        return bundle

    # Expected data freshness: dataset -> (expected_frequency, max_allowed_lag_days)
    _FRESHNESS_RULES: Dict[str, tuple] = {
        # Daily futures/spot/equity: allow 5 days for weekends + holidays
        "pork_futures": ("daily", 5), "pork_futures_far": ("daily", 5),
        "egg_futures": ("daily", 5), "soybean_meal_futures": ("daily", 5),
        "corn_futures": ("daily", 5), "soybean_domestic_futures": ("daily", 5),
        "soybean_import_futures": ("daily", 5), "rapeseed_meal_futures": ("daily", 5),
        "soybean_oil_futures": ("daily", 5), "crude_oil_futures": ("daily", 5),
        "thermal_coal_futures": ("daily", 5), "copper_futures": ("daily", 5),
        "aluminum_futures": ("daily", 5), "rebar_futures": ("daily", 5),
        "gold_futures": ("daily", 5), "silver_futures": ("daily", 5),
        "iron_ore_futures": ("daily", 5), "natural_gas_futures": ("daily", 5),
        "brent_oil": ("daily", 5), "cbot_soybean": ("daily", 5),
        "pork_spot": ("daily", 5), "chicken_spot": ("daily", 5),
        "gold_spot": ("daily", 5), "silver_spot": ("daily", 5),
        "copper_spot": ("daily", 5), "corn_spot": ("daily", 5), "soybean_meal_spot": ("daily", 5),
        "egg_spot": ("daily", 5), "soybean_oil_spot": ("daily", 5), "rapeseed_meal_spot": ("daily", 5),
        "rebar_spot": ("daily", 5), "iron_ore_spot": ("daily", 5),
        "breeding_etf": ("daily", 5), "gold_etf": ("daily", 5),
        "petrochina_stock": ("daily", 5),
        "vix": ("daily", 5), "usd_cny": ("daily", 5),
        "tips_yield": ("daily", 5),
        # Weekly data
        "eia_crude_stock": ("weekly", 10),
        # Monthly macro data
        "cpi": ("monthly", 45), "pmi": ("monthly", 45),
        "m2": ("monthly", 45), "social_financing": ("monthly", 45),
        "us_cpi": ("monthly", 45),
    }

    def get_driver_status(self, chain_def) -> Dict[str, Dict[str, Any]]:
        """Check driver availability with data freshness details.

        Returns:
            {"futures": {"pork_futures": {
                "status": "ok", "last_date": "2026-05-22", "lag_days": 2,
                "expected_frequency": "daily", "max_allowed_lag": 5, "reason": ""
            }, ...}, ...}
        """
        from core.price_schema import KNOWN_MISSING_PRICE_DATA
        from datetime import datetime, timedelta
        drivers = getattr(chain_def, "drivers", {}) or {}
        status: Dict[str, Dict[str, Any]] = {}
        today = datetime.now().date()
        for group, deps in drivers.items():
            group_status: Dict[str, Any] = {}
            for dep_name in (deps if isinstance(deps, list) else []):
                path = self._data_dir / f"{dep_name}.parquet"
                if not path.exists():
                    if dep_name in KNOWN_MISSING_PRICE_DATA:
                        group_status[dep_name] = {
                            "status": "missing_known",
                            "last_date": None, "lag_days": None,
                            "expected_frequency": None, "max_allowed_lag": None,
                            "reason": f"{dep_name} 在已知缺失列表中",
                        }
                    else:
                        group_status[dep_name] = {
                            "status": "missing_unexpected",
                            "last_date": None, "lag_days": None,
                            "expected_frequency": None, "max_allowed_lag": None,
                            "reason": f"{dep_name}.parquet 文件不存在",
                        }
                    continue

                # Read last date from parquet
                try:
                    df = pd.read_parquet(path, columns=["date"])
                    df["date"] = pd.to_datetime(df["date"])
                    last_date = df["date"].max().date()
                    lag_days = (today - last_date).days
                except Exception:
                    last_date = None
                    lag_days = None

                freq, max_lag = self._FRESHNESS_RULES.get(dep_name, ("daily", 5))

                if lag_days is not None and lag_days > max_lag:
                    st = "stale"
                    reason = f"数据过期: 最后日期 {last_date}, 已过期 {lag_days} 天 (允许 {max_lag} 天)"
                else:
                    st = "ok"
                    reason = ""

                group_status[dep_name] = {
                    "status": st,
                    "last_date": str(last_date) if last_date else None,
                    "lag_days": lag_days,
                    "expected_frequency": freq,
                    "max_allowed_lag": max_lag,
                    "reason": reason,
                }
            status[group] = group_status
        return status

    @property
    def cache_stats(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._cache.items()}