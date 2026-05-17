"""
玉米因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：玉米价格极端值 → 均值回归                                           │
│   Z-score<-2 → 超卖 → BUY（玉米是饲料核心原料，低价不可持续）                    │
│   Z-score>2 → 超买 → SELL                                              │
│                                                                     │
│ 链条2：玉米价格异动 → 饲料成本传导                                          │
│   玉米单日涨>2% → 饲料成本上升 → 养殖利润压缩 → SELL 养殖ETF                    │
│   玉米单日跌>2% → 饲料成本下降 → 养殖利润改善 → BUY 养殖ETF                     │
│   [逻辑：玉米占饲料配方60%，是养殖成本最大变量，2%波动即可影响养殖利润]               │
│                                                                     │
│ 注意：猪粮比逻辑已移至 pig_grain_ratio.py，此处仅保留玉米自身价格信号              │
│ 数据：玉米期货(ak.futures_main_sina C)                                    │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="corn", category="feed",
    description="玉米期货异动 + 饲料成本传导 → 养殖信号",
    asset="玉米期货(C)", data_deps=["corn_futures"]
)
class CornFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "zscore_20d": None, "percentile_20d": None,
            "adaptive_threshold": None,
        }

        df = self.load("corn_futures")
        if df is None or len(df) < 2:
            return result

        features = self._multi_window_features(df)
        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(df) >= 20:
            close_series = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close_series.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close_series.tail(20)) if current else None
            result["adaptive_threshold"] = self._adaptive_threshold("corn_change", 0.02, close_series)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        threshold = data.get("adaptive_threshold", 0.02)
        zscore_threshold = self.params.get("zscore_threshold", 2.0)

        if zscore is not None and zscore <= -zscore_threshold:
            return self._make_signal(
                asset="玉米期货(C)", direction="BUY",
                reason=f"玉米Z-score={zscore:.1f}，极端低位→饲料核心原料超卖→反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="corn_extreme_low", zscore=zscore,
            )

        if change is not None and threshold and change >= threshold:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="SELL",
                reason=f"玉米单日涨{change*100:.1f}%→饲料成本上升→养殖利润压缩→养殖股承压",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=-0.50, trigger="corn_surge_cost_pressure", daily_change=change,
            )

        if change is not None and threshold and change <= -threshold:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="BUY",
                reason=f"玉米单日跌{abs(change)*100:.1f}%→饲料成本下降→养殖利润改善→养殖股受益",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=0.50, trigger="corn_drop_cost_relief", daily_change=change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile = data.get("percentile_20d")
        change = data.get("daily_change")
        return self._continuous_signal(zscore, percentile, change)