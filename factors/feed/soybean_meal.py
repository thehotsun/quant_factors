"""
豆粕因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：豆粕价格极端值 → 均值回归                                           │
│   Z-score<-2 → 超卖 → BUY 豆粕（饲料蛋白核心原料，低价不可持续）                │
│   [逻辑：豆粕是饲料蛋白主要来源（占配方25%），极端低价会刺激需求回升]              │
│                                                                     │
│ 链条2：豆粕价格异动 → 饲料成本传导 → 养殖利润                                  │
│   豆粕单日涨>4% → 饲料成本急升 → 养殖利润压缩 → SELL 养殖ETF                    │
│   [逻辑：豆粕占饲料成本25%，短期暴涨直接压缩养殖利润]                            │
│                                                                     │
│ 上游驱动（非本因子直接监测，但需了解）：                                       │
│   - 进口大豆到港量 → 压榨开工率 → 豆粕供给                                    │
│   - 养殖存栏量 → 豆粕需求（生猪存栏↑→豆粕需求↑）                                │
│   - 豆油价格 → 压榨利润 → 豆粕副产品供给                                      │
│                                                                     │
│ 数据：豆粕期货(ak.futures_main_sina M)                                    │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="soybean_meal", category="feed",
    description="豆粕期货异动 → 饲料成本传导：豆粕涨→饲料成本涨→养殖利润压缩",
    asset="豆粕期货(M)", data_deps=["soybean_meal_futures"]
)
class SoybeanMealFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "yesterday_price": None,
            "daily_change": None, "zscore_20d": None,
            "percentile_20d": None, "adaptive_z_threshold": None,
        }

        df = self.load("soybean_meal_futures")
        if df is None or len(df) < 2:
            return result

        features = self._multi_window_features(df)
        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["yesterday_price"] = yesterday
        result["daily_change"] = change
        result.update(features)

        if len(df) >= 20:
            close_series = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close_series.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close_series.tail(20)) if current else None
            result["adaptive_z_threshold"] = self._adaptive_zscore_threshold(close_series)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        z_threshold = data.get("adaptive_z_threshold", 2.0)

        if zscore is not None and zscore <= -z_threshold:
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"豆粕Z-score={zscore:.1f}，处于极端低位",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=min(1.0, abs(zscore) / z_threshold * 0.8),
                trigger="meal_zscore_low", zscore=zscore,
            )

        if change is not None and change >= 0.04:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="SELL",
                reason=f"豆粕单日上涨{change*100:.1f}%，饲料成本上升→养殖利润压缩",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=-0.6, trigger="meal_surge_cost_pressure", daily_change=change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile = data.get("percentile_20d")
        change = data.get("daily_change")
        return self._continuous_signal(zscore, percentile, change)