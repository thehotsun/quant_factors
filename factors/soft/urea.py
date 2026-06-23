"""
尿素因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 尿素（Urea）— 农业化肥永续需求                                         │
│                                                                     │
│ 链条1：农业需求 → 化肥消费（占尿素需求60%）                             │
│   春耕/秋播 → 化肥需求旺季 → 尿素需求↑                                │
│   粮价↑ → 农民施肥意愿↑ → 尿素需求↑                                   │
│                                                                     │
│ 链条2：工业需求 → 三聚氰胺/脲醛树脂（占20%）                            │
│   房地产/基建 → 板材需求 → 三聚氰胺 → 尿素需求                         │
│                                                                     │
│ 链条3：成本端 → 煤炭/天然气                                            │
│   中国70%尿素用煤头工艺 → 煤价↑ → 尿素成本↑ → 尿素价↑                  │
│                                                                     │
│ 链条4：季节性                                                          │
│   3-5月（春耕旺季）→ 需求高峰                                         │
│   9-10月（秋播备肥）→ 需求次高峰                                      │
│   6-8月（用肥淡季）→ 需求低谷                                         │
│   11-2月（冬储期）→ 关注储备需求                                      │
│                                                                     │
│ 散户入口：                                                            │
│   - 尿素期货(UR) 郑商所                                              │
│   - 阳煤化工(600691)、华鲁恒升(600426)                                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from datetime import datetime
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="urea", category="chemicals",
    description="尿素：农业化肥永续需求，春耕/秋播季节性+煤炭成本驱动",
    asset="尿素期货(UR)", data_deps=["urea_futures"]
)
class UreaFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "percentile_250d": None,
            "season": None, "is_peak_season": None,
        }

        df = self.load("urea_futures")
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
        if month in [3, 4, 5]:
            result["season"] = "春耕旺季→化肥需求高峰→尿素需求上升"
            result["is_peak_season"] = True
        elif month in [9, 10]:
            result["season"] = "秋播备肥→需求次高峰"
            result["is_peak_season"] = True
        elif month in [6, 7, 8]:
            result["season"] = "用肥淡季→需求低谷"
            result["is_peak_season"] = False
        else:
            result["season"] = "冬储期→关注储备需求"
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
                asset="尿素期货(UR)", direction="BUY",
                reason=f"尿素Z-score={zscore:.1f}极端低位+用肥旺季→超卖反弹确定性高",
                holding_days=15, stop_loss=-0.04, confidence=0.65,
                strength=0.65, trigger="urea_extreme_low_peak_season",
                zscore=zscore,
            )

        if zscore <= -2.0:
            return self._make_signal(
                asset="尿素期货(UR)", direction="BUY",
                reason=f"尿素Z-score={zscore:.1f}极端低位→成本支撑+减产→反弹预期",
                holding_days=10, stop_loss=-0.04, confidence=0.55,
                strength=0.55, trigger="urea_extreme_low",
                zscore=zscore,
            )

        if percentile_250 is not None and percentile_250 < 20 and is_peak:
            return self._make_signal(
                asset="尿素期货(UR)", direction="BUY",
                reason=f"尿素处于近1年{percentile_250:.0f}%低位+旺季→价格低估+需求支撑",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="urea_low_percentile_peak",
                percentile_250d=percentile_250,
            )

        if zscore >= 2.0:
            return self._make_signal(
                asset="尿素期货(UR)", direction="SELL",
                reason=f"尿素Z-score={zscore:.1f}极端高位→供给恢复→回调",
                holding_days=10, stop_loss=-0.04, confidence=0.55,
                strength=0.55, trigger="urea_extreme_high",
                zscore=zscore,
            )

        if trend == "下跌" and zscore < -1.5:
            return self._make_signal(
                asset="尿素期货(UR)", direction="BUY",
                reason=f"尿素趋势下跌+Z-score={zscore:.1f}接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="urea_trend_break_oversold",
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
            strength += 0.10
        return max(-1.0, min(1.0, strength))
