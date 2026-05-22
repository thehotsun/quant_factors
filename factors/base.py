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
        clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(clean) < 2:
            return 0.0
        mean = clean.mean()
        std = clean.std()
        if std == 0 or np.isnan(std):
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
        clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(clean) < 2:
            return base
        vol = clean.pct_change().replace([np.inf, -np.inf], np.nan).dropna().std()
        if np.isnan(vol):
            return base
        adjustment = 1.0 + max(0.0, (vol - 0.01) * vol_sensitivity)
        result = base * adjustment
        self._threshold_cache[cache_key] = result
        return result

    def _adaptive_zscore_threshold(self, series: pd.Series, base_z: float = 2.0) -> float:
        """自适应 Z-score 阈值：基于近期分布宽度调整"""
        if not self.adaptive:
            return base_z
        recent = pd.to_numeric(series.tail(60), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        long_term = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(recent) < 2 or len(long_term) < 2:
            return base_z
        recent_std = recent.std()
        long_std = long_term.std()
        if long_std == 0 or np.isnan(long_std) or np.isnan(recent_std):
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

    def _realized_vol(self, df: pd.DataFrame, col: str = 'close', window: int = 20) -> Optional[float]:
        """Compute annualized realized volatility from daily returns."""
        try:
            series = df[col].astype(float).tail(window + 1)
            if len(series) < 3:
                return None
            daily_vol = series.pct_change().dropna().std()
            if np.isnan(daily_vol) or daily_vol == 0:
                return None
            return float(daily_vol * np.sqrt(252))
        except Exception:
            return None

    def _volatility_stop(self, df: pd.DataFrame, holding_days: int = 5,
                         col: str = 'close', window: int = 20, k: float = 2.0) -> Optional[float]:
        """Compute volatility-calibrated stop-loss.

        Formula: stop_loss = -k * realized_vol_daily * sqrt(holding_days)
        Capped at -15% to avoid extreme values on very volatile assets.
        """
        try:
            series = df[col].astype(float).tail(window + 1)
            if len(series) < 3:
                return None
            daily_vol = series.pct_change().dropna().std()
            if np.isnan(daily_vol) or daily_vol == 0:
                return None
            stop = -k * daily_vol * np.sqrt(holding_days)
            return max(-0.15, round(float(stop), 4))
        except Exception:
            return None

    def _rolling_percentile(self, value: float, series: pd.Series, window: int = 250) -> float:
        """Compute the percentile of value within the rolling window.

        Returns 0–100.  Used to replace fixed absolute thresholds with
        history-relative position.
        """
        clean = pd.to_numeric(series.tail(window), errors="coerce").dropna()
        if len(clean) < 5:
            return 50.0  # neutral default
        return float((clean < value).sum() / len(clean) * 100)

    def _rolling_zscore(self, value: float, series: pd.Series, window: int = 250) -> float:
        """Compute the z-score of value within the rolling window.

        Used to replace fixed thresholds with statistical deviation.
        """
        clean = pd.to_numeric(series.tail(window), errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(clean) < 5:
            return 0.0
        mean = clean.mean()
        std = clean.std()
        if std == 0 or np.isnan(std):
            return 0.0
        return float((value - mean) / std)

    def _percentile_signal(self, value: float, series: pd.Series,
                           low_pct: float = 20, high_pct: float = 80,
                           window: int = 250) -> str:
        """Classify value as buy/sell/hold based on historical percentile.

        value below low_pct → BUY (undervalued)
        value above high_pct → SELL (overvalued)
        otherwise → HOLD
        """
        pct = self._rolling_percentile(value, series, window)
        if pct <= low_pct:
            return "BUY"
        if pct >= high_pct:
            return "SELL"
        return "HOLD"

    def _zscore_signal(self, value: float, series: pd.Series,
                       buy_z: float = -2.0, sell_z: float = 2.0,
                       window: int = 250) -> str:
        """Classify value as buy/sell/hold based on z-score.

        value z-score below buy_z → BUY (oversold)
        value z-score above sell_z → SELL (overbought)
        otherwise → HOLD
        """
        z = self._rolling_zscore(value, series, window)
        if z <= buy_z:
            return "BUY"
        if z >= sell_z:
            return "SELL"
        return "HOLD"

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
                     confidence: float = 0.5, strength: float = None,
                     factor_value_type: str = None, factor_direction: str = None,
                     horizon_days: int = None,
                     factor_score: float = None, risk_modifier: float = None,
                     price_df=None,
                     **kwargs) -> Dict[str, Any]:
        raw_strength = strength if strength is not None else (0.5 if direction == "BUY" else -0.5)
        try:
            normalized_strength = max(-1.0, min(1.0, float(raw_strength)))
        except (TypeError, ValueError):
            normalized_strength = 0.0

        try:
            normalized_confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            normalized_confidence = 0.5

        # trade_signal_strength: direction-aligned trade conviction.
        # Positive = BUY conviction, negative = SELL conviction, 0 = HOLD.
        # Unlike raw `strength`, this is always consistent with `direction`.
        if direction == "BUY":
            trade_signal_strength = abs(normalized_strength)
        elif direction == "SELL":
            trade_signal_strength = -abs(normalized_strength)
        else:
            trade_signal_strength = 0.0

        meta = kwargs.pop("meta", {}) or {}
        trigger = kwargs.get("trigger")
        factor_value = kwargs.pop("factor_value", None)

        # Volatility-calibrated stop: if price_df provided, compute from realized vol
        if price_df is not None:
            vol_stop = self._volatility_stop(price_df, holding_days=holding_days)
            if vol_stop is not None:
                stop_loss = vol_stop

        signal = {
            "asset": asset,
            "direction": direction,
            "strength": normalized_strength,
            "signal_strength": normalized_strength,
            "trade_signal_strength": round(trade_signal_strength, 4),
            "reason": reason,
            "holding_days": holding_days,
            "stop_loss": stop_loss,
            "confidence": normalized_confidence,
            "trigger": trigger,
            "factor_value": factor_value,
            "factor_value_type": factor_value_type,
            "factor_direction": factor_direction,
            "horizon_days": horizon_days or holding_days,
            "factor_score": factor_score,
            "risk_modifier": risk_modifier,
            "meta": meta,
        }
        # Keep legacy flat fields for current API consumers, while also
        # grouping non-standard extras under meta for a stable schema.
        signal.update(kwargs)
        for key, value in kwargs.items():
            if key not in {"trigger"}:
                signal["meta"].setdefault(key, value)
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