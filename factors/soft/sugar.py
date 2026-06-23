"""
白糖因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 白糖（White Sugar）— 永续需求，甘蔗/甜菜种植周期驱动                    │
│                                                                     │
│ 链条1：全球供需 → 库存消费比                                          │
│   巴西/印度/泰国甘蔗产量 → 全球供给                                   │
│   库存消费比↓ → 供给偏紧 → 糖价上行                                   │
│                                                                     │
│ 链条2：国内政策 → 进口配额 + 收储                                     │
│   进口配额收紧 → 国内供给偏紧 → 糖价↑                                 │
│   国家收储 → 托底糖价                                                │
│                                                                     │
│ 链条3：种植周期（3-4年）                                              │
│   糖价高→扩种→3年后供给过剩→糖价跌→减种→3年后供给紧缺→糖价涨           │
│                                                                     │
│ 链条4：天气 → 厄尔尼诺/拉尼娜                                        │
│   干旱→甘蔗减产→糖价脉冲上涨                                         │
│                                                                     │
│ 散户入口：                                                            │
│   - 白糖期货(SR) 郑商所                                              │
│   - 南宁糖业(000911)、中粮糖业(600737)                                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="sugar", category="soft",
    description="白糖：永续需求，甘蔗种植周期3-4年+全球库存消费比驱动",
    asset="白糖期货(SR)", data_deps=["sugar_futures"]
)
class SugarFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "percentile_250d": None,
            "volatility_20d": None,
        }

        df = self.load("sugar_futures")
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

        result["factor_value"] = result.get("zscore_20d")
        result["factor_value_type"] = "zscore" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile_250 = data.get("percentile_250d")
        trend = data.get("trend")

        if zscore is None:
            return None

        if zscore <= -2.0:
            return self._make_signal(
                asset="白糖期货(SR)", direction="BUY",
                reason=f"白糖Z-score={zscore:.1f}极端低位→减种周期+收储预期→反弹",
                holding_days=15, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="sugar_extreme_low",
                zscore=zscore,
            )

        if percentile_250 is not None and percentile_250 < 20:
            return self._make_signal(
                asset="白糖期货(SR)", direction="BUY",
                reason=f"白糖处于近1年{percentile_250:.0f}%低位→价格低估+种植周期底部",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="sugar_low_percentile",
                percentile_250d=percentile_250,
            )

        if zscore >= 2.0:
            return self._make_signal(
                asset="白糖期货(SR)", direction="SELL",
                reason=f"白糖Z-score={zscore:.1f}极端高位→扩种预期+供给恢复→回调",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="sugar_extreme_high",
                zscore=zscore,
            )

        if trend == "下跌" and zscore < -1.5:
            return self._make_signal(
                asset="白糖期货(SR)", direction="BUY",
                reason=f"白糖趋势下跌+Z-score={zscore:.1f}接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="sugar_trend_break_oversold",
                trend=trend, zscore=zscore,
            )

        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        if zscore is None:
            return 0.0
        return max(-1.0, min(1.0, zscore / 3.0))
