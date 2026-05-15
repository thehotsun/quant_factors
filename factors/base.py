from pathlib import Path
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from abc import ABC, abstractmethod
from datetime import datetime
from core.data_bus import DataBus


class BaseFactor(ABC):
    """增强版因子基类

    新增能力：
    - DataBus 统一数据加载（避免重复 I/O）
    - 自适应阈值（基于滚动波动率动态校准）
    - 连续信号强度（-1.0 ~ +1.0，替代二元 BUY/SELL）
    - 因子元信息（name/category/version/params）
    - 多窗口特征工程辅助方法
    """

    def __init__(self, data_dir: str = "./data", adaptive: bool = True,
                 params: Dict[str, Any] = None):
        self.data_dir = Path(data_dir)
        self.adaptive = adaptive
        self.params = params or {}
        self._bus = DataBus(data_dir)
        self._threshold_cache: Dict[str, float] = {}
        self._cached_data: Optional[Dict[str, Any]] = None

    def load(self, name: str, date_col: str = 'date') -> Optional[pd.DataFrame]:
        return self._bus.get(name, date_col)

    def _get_or_calculate(self) -> Dict[str, Any]:
        if self._cached_data is not None:
            return self._cached_data
        return self.calculate()

    def _safe_float(self, series, idx: int = -1, col: str = 'close') -> Optional[float]:
        try:
            val = series.iloc[idx]
            if isinstance(val, pd.Series):
                val = val.get(col, val.iloc[0] if len(val) > 0 else None)
            return float(val) if val is not None and not np.isnan(val) else None
        except (IndexError, TypeError, ValueError):
            return None

    def _pct_change(self, current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / previous

    def _zscore(self, value: float, series: pd.Series) -> float:
        mean = series.mean()
        std = series.std()
        if std == 0:
            return 0.0
        return (value - mean) / std

    def _percentile(self, value: float, series: pd.Series) -> float:
        return (series < value).sum() / len(series)

    def _adaptive_threshold(self, name: str, base: float, series: pd.Series,
                            vol_sensitivity: float = 50.0) -> float:
        """自适应阈值：波动率越高，阈值越宽（避免频繁触发）"""
        if not self.adaptive:
            return base
        cache_key = f"{name}_{len(series)}_{base}"
        if cache_key in self._threshold_cache:
            return self._threshold_cache[cache_key]
        vol = series.pct_change().std()
        adjustment = 1.0 + max(0.0, (vol - 0.01) * vol_sensitivity)
        result = base * adjustment
        self._threshold_cache[cache_key] = result
        return result

    def _adaptive_zscore_threshold(self, series: pd.Series, base_z: float = 2.0) -> float:
        """自适应 Z-score 阈值：基于近期分布宽度调整"""
        if not self.adaptive:
            return base_z
        recent = series.tail(60)
        long_term = series
        recent_std = recent.std()
        long_std = long_term.std()
        if long_std == 0:
            return base_z
        ratio = recent_std / long_std
        return base_z * (0.8 + 0.4 * ratio)

    def _multi_window_features(self, df: pd.DataFrame, col: str = 'close',
                                windows: List[int] = None) -> Dict[str, float]:
        """多窗口时序特征工程"""
        if windows is None:
            windows = [5, 10, 20, 60]
        series = df[col].astype(float)
        current = float(series.iloc[-1])
        features = {"current": current}

        for w in windows:
            if len(series) >= w + 1:
                past = float(series.iloc[-w - 1])
                features[f"change_{w}d"] = (current - past) / past if past != 0 else None
                features[f"ma_{w}d"] = float(series.tail(w).mean())
                features[f"vol_{w}d"] = float(series.pct_change().tail(w).std())

        if len(series) >= 20:
            returns = series.pct_change().dropna()
            features["skew_20d"] = float(returns.tail(20).skew())
            features["kurt_20d"] = float(returns.tail(20).kurtosis())
            features["max_dd_20d"] = float((series.tail(20) / series.tail(20).cummax() - 1).min())

        if len(series) >= 14:
            features["rsi_14d"] = self._rsi(series, 14)

        return features

    def _rsi(self, series: pd.Series, period: int = 14) -> float:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))

        avg_gain = float(gain.iloc[1:period + 1].mean())
        avg_loss = float(loss.iloc[1:period + 1].mean())

        for i in range(period + 1, len(gain)):
            avg_gain = (avg_gain * (period - 1) + float(gain.iloc[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(loss.iloc[i])) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - 100.0 / (1.0 + rs))

    def _continuous_signal(self, zscore: Optional[float], percentile: Optional[float] = None,
                           change: Optional[float] = None, change_is_cost: bool = True) -> float:
        """将统计量映射为连续信号强度 (-1.0 ~ +1.0)

        zscore < -2 → 强买入信号 (+1.0)
        zscore > +2 → 强卖出信号 (-1.0)
        使用 sigmoid 平滑过渡

        change_is_cost=True: 价格上涨=利空（适用于成本类因子，如豆粕/玉米）
        change_is_cost=False: 价格上涨=利好（适用于资产类因子，如原油/铜）
        """
        strength = 0.0
        weight_sum = 0.0

        if zscore is not None:
            w = 0.5
            strength += w * (2.0 / (1.0 + np.exp(zscore)) - 1.0)
            weight_sum += w

        if percentile is not None:
            w = 0.3
            strength += w * (1.0 - 2.0 * percentile)
            weight_sum += w

        if change is not None:
            w = 0.2
            direction = -1.0 if change_is_cost else 1.0
            strength += w * (direction * np.tanh(change * 20))
            weight_sum += w

        if weight_sum == 0:
            return 0.0
        return max(-1.0, min(1.0, strength / weight_sum))

    def _make_signal(self, asset: str, direction: str, reason: str,
                     holding_days: int = 5, stop_loss: float = -0.02,
                     confidence: float = 0.5, strength: float = None, **kwargs) -> Dict[str, Any]:
        signal = {
            "asset": asset,
            "direction": direction,
            "strength": strength if strength is not None else (0.5 if direction == "BUY" else -0.5),
            "reason": reason,
            "holding_days": holding_days,
            "stop_loss": stop_loss,
            "confidence": confidence,
        }
        signal.update(kwargs)
        return signal

    @abstractmethod
    def calculate(self) -> Dict[str, Any]:
        pass

    def signal(self) -> Optional[Dict[str, Any]]:
        """默认信号方法，子类可覆盖。返回 None 表示无信号"""
        return None

    def signal_strength(self) -> float:
        """连续信号强度：-1.0(强烈卖出) ~ +1.0(强烈买入)，0.0 表示中性"""
        return 0.0