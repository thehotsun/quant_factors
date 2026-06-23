"""
纯碱因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 纯碱（Soda Ash）— 玻璃核心原料，永续需求                                │
│                                                                     │
│ 链条1：玻璃需求 → 纯碱消费（占纯碱需求35%）                             │
│   房地产竣工↑ → 浮法玻璃需求↑ → 纯碱需求↑ → 纯碱价↑                    │
│   光伏装机↑ → 光伏玻璃需求↑ → 纯碱需求↑                                │
│                                                                     │
│ 链条2：供给端 → 环保限产 + 产能投放周期                                  │
│   能耗双控 → 纯碱限产 → 供给收缩 → 涨价                                │
│   新产能投放（如远兴天然碱）→ 供给增加 → 跌价                           │
│                                                                     │
│ 链条3：季节性                                                          │
│   春季开工+秋季赶工 → 玻璃旺季 → 纯碱需求高峰                          │
│   冬季停工 → 需求低谷                                                  │
│                                                                     │
│ 散户入口：                                                            │
│   - 纯碱期货(SA) 郑商所                                              │
│   - 远兴能源(000683)、三友化工(600409)                                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from datetime import datetime
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="soda_ash", category="chemicals",
    description="纯碱：玻璃核心原料，光伏新增需求+环保限产→供给端周期性调整",
    asset="纯碱期货(SA)", data_deps=["soda_ash_futures"]
)
class SodaAshFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "percentile_250d": None,
            "season": None, "is_peak_season": None,
        }

        df = self.load("soda_ash_futures")
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
        if month in [3, 4, 5, 9, 10, 11]:
            result["season"] = "开工旺季→玻璃需求高峰→纯碱需求上升"
            result["is_peak_season"] = True
        elif month in [12, 1, 2]:
            result["season"] = "冬季停工→需求低谷"
            result["is_peak_season"] = False
        else:
            result["season"] = "夏季→需求平稳"
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
                asset="纯碱期货(SA)", direction="BUY",
                reason=f"纯碱Z-score={zscore:.1f}极端低位+开工旺季→超卖反弹确定性高",
                holding_days=15, stop_loss=-0.05, confidence=0.70,
                strength=0.70, trigger="soda_ash_extreme_low_peak_season",
                zscore=zscore,
            )

        if zscore <= -2.0:
            return self._make_signal(
                asset="纯碱期货(SA)", direction="BUY",
                reason=f"纯碱Z-score={zscore:.1f}极端低位→产能收缩+成本支撑→反弹预期",
                holding_days=10, stop_loss=-0.05, confidence=0.60,
                strength=0.60, trigger="soda_ash_extreme_low",
                zscore=zscore,
            )

        if percentile_250 is not None and percentile_250 < 20 and is_peak:
            return self._make_signal(
                asset="纯碱期货(SA)", direction="BUY",
                reason=f"纯碱处于近1年{percentile_250:.0f}%低位+旺季→价格低估+需求支撑",
                holding_days=10, stop_loss=-0.04, confidence=0.55,
                strength=0.55, trigger="soda_ash_low_percentile_peak",
                percentile_250d=percentile_250,
            )

        if zscore >= 2.0:
            return self._make_signal(
                asset="纯碱期货(SA)", direction="SELL",
                reason=f"纯碱Z-score={zscore:.1f}极端高位→新产能投放+供给恢复→回调",
                holding_days=10, stop_loss=-0.05, confidence=0.55,
                strength=0.55, trigger="soda_ash_extreme_high",
                zscore=zscore,
            )

        if trend == "下跌" and zscore < -1.5:
            return self._make_signal(
                asset="纯碱期货(SA)", direction="BUY",
                reason=f"纯碱趋势下跌+Z-score={zscore:.1f}接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.04, confidence=0.50,
                strength=0.50, trigger="soda_ash_trend_break_oversold",
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
