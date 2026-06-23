"""
橡胶因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 橡胶（Rubber）— 永续需求工业品，种植周期7-10年                            │
│                                                                     │
│ 链条1：种植周期 → 供给端滞后                                           │
│   橡胶树种下5-7年才能开割，价格下跌→砍树→供给减少→价格回升                  │
│   价格上涨→扩种→5-7年后供给大增→价格下跌                                 │
│   典型周期：2011年32000 → 2018年11000 → 2024年16000                    │
│                                                                     │
│ 链条2：季节性停割 → 短期供给冲击                                        │
│   12-3月：东南亚停割期（落叶季），供给季节性收紧                           │
│   4-11月：割胶季，供给恢复                                              │
│                                                                     │
│ 链条3：下游需求 → 轮胎/汽车产业链                                       │
│   轮胎占天然橡胶消费70%，汽车产销→轮胎需求→橡胶需求                       │
│                                                                     │
│ 散户入口：                                                            │
│   - 橡胶期货(RU) 上期所                                              │
│   - 赛轮轮胎(601058)、玲珑轮胎(601966)                                │
│   - 海南橡胶(601118)（橡胶种植龙头）                                    │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from datetime import datetime
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="rubber", category="soft",
    description="橡胶：轮胎/密封件永续需求，种植周期7-10年+季节停割→供给端周期性调整",
    asset="橡胶期货(RU)", data_deps=["rubber_futures"]
)
class RubberFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "percentile_250d": None,
            "season": None, "is_peak_season": None,
        }

        df = self.load("rubber_futures")
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

        if len(df) >= 60:
            close = df['close'].astype(float)
            result["ma20"] = round(float(close.tail(20).mean()), 2)
            result["ma60"] = round(float(close.tail(60).mean()), 2)
            result["trend"] = "上涨" if result["ma20"] > result["ma60"] else "下跌"

        if len(df) >= 20:
            close = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None

        if len(df) >= 250:
            close = df['close'].astype(float)
            result["percentile_250d"] = round(self._rolling_percentile(current, close, 250), 1)

        month = datetime.now().month
        if month in [12, 1, 2, 3]:
            result["season"] = "停割期→供给季节性收紧→利多橡胶价"
            result["is_peak_season"] = True
        elif month in [4, 5]:
            result["season"] = "割胶初期→供给逐步恢复→中性偏空"
            result["is_peak_season"] = False
        else:
            result["season"] = "割胶旺季→供给充裕→利空橡胶价"
            result["is_peak_season"] = False

        result["factor_value"] = result.get("zscore_20d")
        result["factor_value_type"] = "zscore" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile_250 = data.get("percentile_250d")
        trend = data.get("trend")
        is_peak = data.get("is_peak_season", False)

        if zscore is None:
            return None

        if zscore <= -2.0 and is_peak:
            return self._make_signal(
                asset="橡胶期货(RU)", direction="BUY",
                reason=f"橡胶Z-score={zscore:.1f}极端低位+停割期供给收紧→超卖反弹确定性高",
                holding_days=15, stop_loss=-0.04, confidence=0.70,
                strength=0.70, trigger="rubber_extreme_low_offseason",
                zscore=zscore,
            )

        if zscore <= -2.0:
            return self._make_signal(
                asset="橡胶期货(RU)", direction="BUY",
                reason=f"橡胶Z-score={zscore:.1f}极端低位→种植周期底部+成本支撑→反弹预期",
                holding_days=10, stop_loss=-0.04, confidence=0.60,
                strength=0.60, trigger="rubber_extreme_low",
                zscore=zscore,
            )

        if percentile_250 is not None and percentile_250 < 20 and is_peak:
            return self._make_signal(
                asset="橡胶期货(RU)", direction="BUY",
                reason=f"橡胶处于近1年{percentile_250:.0f}%低位+停割期→价格低估+季节性支撑",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="rubber_low_percentile_offseason",
                percentile_250d=percentile_250,
            )

        if zscore >= 2.0:
            return self._make_signal(
                asset="橡胶期货(RU)", direction="SELL",
                reason=f"橡胶Z-score={zscore:.1f}极端高位→扩种预期+供给恢复→回调风险",
                holding_days=10, stop_loss=-0.04, confidence=0.55,
                strength=0.55, trigger="rubber_extreme_high",
                zscore=zscore,
            )

        if trend == "下跌" and zscore < -1.5:
            return self._make_signal(
                asset="橡胶期货(RU)", direction="BUY",
                reason=f"橡胶趋势下跌+Z-score={zscore:.1f}接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="rubber_trend_break_oversold",
                trend=trend, zscore=zscore,
            )

        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if data.get("is_peak_season"):
            strength += 0.15
        return max(-1.0, min(1.0, strength))
