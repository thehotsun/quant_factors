"""
棉花因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 棉花（Cotton）— 永续需求农产品，全球库存消费比驱动5-7年周期               │
│                                                                     │
│ 链条1：全球库存消费比 → 中长期供需格局（最核心驱动）                      │
│   库存消费比↓ → 供给偏紧 → 棉价上行                                    │
│   库存消费比↑ → 供给宽松 → 棉价下行                                    │
│                                                                     │
│ 链条2：季节性 → 新棉上市节奏                                           │
│   9-11月：新棉集中上市 → 供给压力                                       │
│   12-2月：纺织旺季（冬装+春节备货）→ 需求高峰                            │
│   3-5月：青黄不接期，库存消化中                                          │
│   6-8月：棉花生长关键期，天气敏感                                        │
│                                                                     │
│ 散户入口：                                                            │
│   - 棉花期货(CF) 郑商所                                              │
│   - 鲁泰A(000726)、华孚时尚(002042)                                   │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from datetime import datetime
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="cotton", category="soft",
    description="棉花：纺织服装永续需求，全球库存消费比驱动5-7年周期+季节性",
    asset="棉花期货(CF)", data_deps=["cotton_futures"]
)
class CottonFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "percentile_250d": None,
            "season": None, "season_bias": None,
        }

        df = self.load("cotton_futures")
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
        if month in [9, 10, 11]:
            result["season"] = "新棉集中上市→供给压力增大"
            result["season_bias"] = "bearish"
        elif month in [12, 1, 2]:
            result["season"] = "纺织旺季（冬装+春节备货）→需求高峰"
            result["season_bias"] = "bullish"
        elif month in [3, 4, 5]:
            result["season"] = "青黄不接期→库存消化中"
            result["season_bias"] = "neutral"
        else:
            result["season"] = "棉花生长关键期→天气敏感"
            result["season_bias"] = "neutral"

        result["factor_value"] = result.get("zscore_20d")
        result["factor_value_type"] = "zscore" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile_250 = data.get("percentile_250d")
        trend = data.get("trend")
        season_bias = data.get("season_bias")

        if zscore is None:
            return None

        if zscore <= -2.0 and season_bias == "bullish":
            return self._make_signal(
                asset="棉花期货(CF)", direction="BUY",
                reason=f"棉花Z-score={zscore:.1f}极端低位+纺织旺季需求高峰→超卖反弹确定性高",
                holding_days=15, stop_loss=-0.04, confidence=0.70,
                strength=0.70, trigger="cotton_extreme_low_peak_season",
                zscore=zscore,
            )

        if zscore <= -2.0:
            return self._make_signal(
                asset="棉花期货(CF)", direction="BUY",
                reason=f"棉花Z-score={zscore:.1f}极端低位→种植面积缩减+库存消费比下降→反弹预期",
                holding_days=10, stop_loss=-0.04, confidence=0.60,
                strength=0.60, trigger="cotton_extreme_low",
                zscore=zscore,
            )

        if percentile_250 is not None and percentile_250 < 20 and season_bias == "bullish":
            return self._make_signal(
                asset="棉花期货(CF)", direction="BUY",
                reason=f"棉花处于近1年{percentile_250:.0f}%低位+纺织旺季→价格低估+需求支撑",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="cotton_low_percentile_peak_season",
                percentile_250d=percentile_250,
            )

        if zscore >= 2.0 and season_bias == "bearish":
            return self._make_signal(
                asset="棉花期货(CF)", direction="SELL",
                reason=f"棉花Z-score={zscore:.1f}极端高位+新棉上市供给压力→回调风险加大",
                holding_days=10, stop_loss=-0.04, confidence=0.60,
                strength=0.60, trigger="cotton_extreme_high_new_crop",
                zscore=zscore,
            )

        if zscore >= 2.0:
            return self._make_signal(
                asset="棉花期货(CF)", direction="SELL",
                reason=f"棉花Z-score={zscore:.1f}极端高位→扩种预期+供给恢复→回调",
                holding_days=10, stop_loss=-0.04, confidence=0.55,
                strength=0.55, trigger="cotton_extreme_high",
                zscore=zscore,
            )

        if trend == "下跌" and zscore < -1.5:
            return self._make_signal(
                asset="棉花期货(CF)", direction="BUY",
                reason=f"棉花趋势下跌+Z-score={zscore:.1f}接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="cotton_trend_break_oversold",
                trend=trend, zscore=zscore,
            )

        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if data.get("season_bias") == "bullish":
            strength += 0.10
        elif data.get("season_bias") == "bearish":
            strength -= 0.10
        return max(-1.0, min(1.0, strength))
