"""
蛋料比因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：蛋料比 → 养殖利润 → 补栏/淘汰决策 → 鸡蛋供给 → 蛋价                       │
│   蛋料比 < 2.5（亏损线）→ 养殖亏损 → 淘汰老鸡 → 供给收缩 → 蛋价↑ → BUY           │
│   蛋料比 > 3.5（暴利线）→ 养殖暴利 → 补栏扩产 → 供给增加 → 蛋价↓ → SELL           │
│   [逻辑：蛋鸡养殖周期约4-5个月，补栏到产蛋有滞后，但利润信号是领先指标]              │
│                                                                     │
│ 链条2：鸡蛋价格异动 → 短期供需                                            │
│   鸡蛋单日跌>自适应阈值 → 超卖 → BUY（短期反弹）                               │
│                                                                     │
│ 饲料配方：玉米60% + 豆粕25% + 预混料/其他15%（折合固定成本200元/吨）               │
│ 数据：鸡蛋期货(JD) + 玉米期货(C) + 豆粕期货(M)                                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="egg_feed_ratio", category="cross",
    description="蛋料比→养殖利润：<2.5亏损→淘汰→供给收缩→BUY；>3.5暴利→补栏→供给增加→SELL",
    asset="鸡蛋期货(JD)", data_deps=["egg_futures", "corn_futures", "soybean_meal_futures"]
)
class EggFeedRatio(BaseFactor):
    BASE_LOSS_THRESHOLD = 2.5
    BASE_PROFIT_THRESHOLD = 3.5

    def calculate(self) -> Dict[str, Any]:
        result = {
            "egg_feed_ratio": None, "egg_price": None, "feed_cost": None,
            "daily_change": None, "zscore_20d": None, "percentile_20d": None,
            "adaptive_threshold": None,
            "adaptive_loss_threshold": None, "adaptive_profit_threshold": None,
        }

        egg_df = self.load("egg_futures")
        if egg_df is None or len(egg_df) < 2:
            return result

        features = self._multi_window_features(egg_df)
        last_two = egg_df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["egg_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(egg_df) >= 20:
            close_series = egg_df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close_series.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close_series.tail(20)) if current else None
            result["adaptive_threshold"] = self._adaptive_threshold("egg_change", 0.03, close_series)

        corn_df = self.load("corn_futures")
        meal_df = self.load("soybean_meal_futures")
        if corn_df is not None and meal_df is not None and current:
            corn_price = self._safe_float(corn_df.tail(1), -1)
            meal_price = self._safe_float(meal_df.tail(1), -1)
            if corn_price and meal_price:
                feed_cost_per_ton = corn_price * 0.60 + meal_price * 0.25 + 200
                feed_cost_per_jin = feed_cost_per_ton / 2000
                egg_price_per_jin = current / 500
                ratio = egg_price_per_jin / feed_cost_per_jin if feed_cost_per_jin > 0 else None
                result["feed_cost"] = round(feed_cost_per_ton, 2)
                result["egg_feed_ratio"] = round(ratio, 2) if ratio else None

            if len(egg_df) >= 60 and len(corn_df) >= 60 and len(meal_df) >= 60:
                merged = pd.merge(
                    egg_df[['date', 'close']].rename(columns={'close': 'egg'}),
                    corn_df[['date', 'close']].rename(columns={'close': 'corn'}),
                    on='date', how='inner'
                )
                merged = pd.merge(
                    merged,
                    meal_df[['date', 'close']].rename(columns={'close': 'meal'}),
                    on='date', how='inner'
                )
                if len(merged) >= 20:
                    merged['feed_cost_per_ton'] = merged['corn'] * 0.60 + merged['meal'] * 0.25 + 200
                    merged['feed_cost_per_jin'] = merged['feed_cost_per_ton'] / 2000
                    merged['egg_price_per_jin'] = merged['egg'] / 500
                    merged['ratio'] = merged['egg_price_per_jin'] / merged['feed_cost_per_jin']
                    ratio_series = merged['ratio'].tail(60)
                    result["adaptive_loss_threshold"] = round(self._adaptive_threshold(
                        "egg_feed_loss", self.BASE_LOSS_THRESHOLD, ratio_series, vol_sensitivity=20
                    ), 2)
                    result["adaptive_profit_threshold"] = round(self._adaptive_threshold(
                        "egg_feed_profit", self.BASE_PROFIT_THRESHOLD, ratio_series, vol_sensitivity=20
                    ), 2)

        result["factor_value"] = result.get("zscore_20d")
        result["factor_value_type"] = "zscore" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("egg_feed_ratio")
        change = data.get("daily_change")
        threshold = data.get("adaptive_threshold", 0.03)
        loss_threshold = data.get("adaptive_loss_threshold", self.BASE_LOSS_THRESHOLD)
        profit_threshold = data.get("adaptive_profit_threshold", self.BASE_PROFIT_THRESHOLD)

        if ratio is not None and ratio < loss_threshold:
            return self._make_signal(
                asset="鸡蛋期货(JD)", direction="BUY",
                reason=f"蛋料比{ratio:.1f}<{loss_threshold:.1f}→养殖亏损→淘汰老鸡→供给收缩→蛋价反弹",
                holding_days=15, stop_loss=-0.03, confidence=0.65,
                strength=min(1.0, (loss_threshold - ratio) / 1.0 + 0.3),
                trigger="egg_feed_loss", egg_feed_ratio=ratio,
            )

        if ratio is not None and ratio > profit_threshold:
            return self._make_signal(
                asset="鸡蛋期货(JD)", direction="SELL",
                reason=f"蛋料比{ratio:.1f}>{profit_threshold:.1f}→养殖暴利→补栏扩产→供给增加→蛋价回落",
                holding_days=15, stop_loss=-0.03, confidence=0.60,
                strength=-min(1.0, (ratio - profit_threshold) / 1.0 + 0.3),
                trigger="egg_feed_profit", egg_feed_ratio=ratio,
            )

        if change is not None and threshold and change <= -threshold:
            return self._make_signal(
                asset="鸡蛋期货(JD)", direction="BUY",
                reason=f"鸡蛋单日跌{abs(change)*100:.1f}%→超卖→短期反弹",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=min(1.0, abs(change) / threshold * 0.7),
                trigger="egg_drop", daily_change=change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio = data.get("egg_feed_ratio")
        zscore = data.get("zscore_20d")
        loss_threshold = data.get("adaptive_loss_threshold", self.BASE_LOSS_THRESHOLD)
        profit_threshold = data.get("adaptive_profit_threshold", self.BASE_PROFIT_THRESHOLD)
        if ratio is None:
            return 0.0
        if ratio < loss_threshold:
            return min(1.0, (loss_threshold - ratio) / 1.0 + 0.3)
        if ratio > profit_threshold:
            return max(-1.0, -(ratio - profit_threshold) / 1.0 - 0.3)
        if zscore is not None:
            return zscore / 3.0
        return 0.0