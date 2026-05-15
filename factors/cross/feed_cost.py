"""
饲料成本指数因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：饲料成本指数 → 养殖利润 → 养殖ETF                                        │
│                                                                     │
│   饲料成本指数单日涨>3% → 养殖成本急升 → 养殖利润压缩 → SELL 养殖ETF               │
│     [逻辑：饲料占养殖成本60-70%，成本急升直接压缩利润空间]                          │
│                                                                     │
│   饲料成本指数处于历史>90%分位 → 成本高位 → 养殖持续承压 → SELL 养殖ETF             │
│     [逻辑：饲料成本长期高位会导致散户退出、行业亏损]                                │
│                                                                     │
│   饲料成本指数处于历史<10%分位 → 成本低位 → 养殖利润改善 → BUY 养殖ETF              │
│     [逻辑：饲料成本低位是养殖板块最确定的利好，直接增厚利润]                          │
│                                                                     │
│ 配方权重：                                                               │
│   玉米 60% — 能量饲料，占比最大，价格波动对成本影响最大                             │
│   豆粕 25% — 蛋白饲料，进口依赖度高，受CBOT大豆+汇率影响                           │
│   菜粕 10% — 替代蛋白，与豆粕存在替代关系                                       │
│   其他  5% — 预混料/添加剂，折合固定成本200元/吨                                  │
│                                                                     │
│ 数据：玉米期货(C) + 豆粕期货(M) + 菜粕期货(RM)                                  │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="feed_cost", category="cross",
    description="饲料成本指数(玉米+豆粕+菜粕) → 养殖利润",
    asset="养殖ETF(159865)", data_deps=["corn_futures", "soybean_meal_futures", "rapeseed_meal_futures"]
)
class FeedCostIndex(BaseFactor):
    BASE_CORN_WEIGHT = 0.60
    BASE_SOYBEAN_MEAL_WEIGHT = 0.25
    BASE_RAPESEED_MEAL_WEIGHT = 0.10
    OTHER_FIXED = 200

    def calculate(self) -> Dict[str, Any]:
        result = {
            "feed_cost_index": None, "corn_price": None,
            "soybean_meal_price": None, "rapeseed_meal_price": None,
            "daily_change": None,
        }

        corn_df = self.load("corn_futures")
        meal_df = self.load("soybean_meal_futures")
        rm_df = self.load("rapeseed_meal_futures")
        if corn_df is None or meal_df is None:
            return result

        corn_current = self._safe_float(corn_df.tail(1), -1)
        meal_current = self._safe_float(meal_df.tail(1), -1)
        rm_current = self._safe_float(rm_df.tail(1), -1) if rm_df is not None else None
        if corn_current is None or meal_current is None:
            return result

        rm_val = rm_current if rm_current else 2500
        index = (corn_current * self.BASE_CORN_WEIGHT +
                 meal_current * self.BASE_SOYBEAN_MEAL_WEIGHT +
                 rm_val * self.BASE_RAPESEED_MEAL_WEIGHT +
                 self.OTHER_FIXED)

        result["corn_price"] = corn_current
        result["soybean_meal_price"] = meal_current
        result["rapeseed_meal_price"] = rm_current
        result["feed_cost_index"] = round(index, 2)

        if len(corn_df) >= 2 and len(meal_df) >= 2:
            corn_prev = self._safe_float(corn_df.tail(2), -2)
            meal_prev = self._safe_float(meal_df.tail(2), -2)
            if corn_prev and meal_prev:
                rm_prev = self._safe_float(rm_df.tail(2), -2) if rm_df is not None and len(rm_df) >= 2 else rm_val
                if rm_prev is None:
                    rm_prev = rm_val
                prev_index = (corn_prev * self.BASE_CORN_WEIGHT +
                              meal_prev * self.BASE_SOYBEAN_MEAL_WEIGHT +
                              rm_prev * self.BASE_RAPESEED_MEAL_WEIGHT +
                              self.OTHER_FIXED)
                result["daily_change"] = self._pct_change(index, prev_index)

        if len(corn_df) >= 20:
            corn_series = corn_df['close'].astype(float).tail(20)
            meal_series = meal_df['close'].astype(float).tail(20)
            min_len = min(len(corn_series), len(meal_series))
            indices = []
            for i in range(max(0, min_len - 20), min_len):
                c = float(corn_series.iloc[i])
                m = float(meal_series.iloc[i])
                indices.append(c * self.BASE_CORN_WEIGHT + m * self.BASE_SOYBEAN_MEAL_WEIGHT +
                               rm_val * self.BASE_RAPESEED_MEAL_WEIGHT + self.OTHER_FIXED)
            if indices:
                idx_series = pd.Series(indices)
                result["index_ma5"] = round(float(idx_series.tail(5).mean()), 2)
                result["index_ma20"] = round(float(idx_series.tail(20).mean()), 2)
                result["index_percentile"] = round(self._percentile(index, idx_series) * 100, 1)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        percentile = data.get("index_percentile")

        if change is not None and change >= 0.03:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="SELL",
                reason=f"饲料成本指数单日上涨{change*100:.1f}%，养殖利润压缩",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=-0.6, trigger="feed_cost_surge",
                feed_cost_index=data.get("feed_cost_index"), daily_change=change,
            )

        if percentile is not None and percentile > 90:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="SELL",
                reason=f"饲料成本处于{percentile:.0f}%分位，历史高位→养殖承压",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=-0.65, trigger="feed_cost_high_percentile",
                feed_cost_index=data.get("feed_cost_index"), percentile=percentile,
            )

        if percentile is not None and percentile < 10:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="BUY",
                reason=f"饲料成本处于{percentile:.0f}%分位，历史低位→养殖利润改善",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.6, trigger="feed_cost_low_percentile",
                feed_cost_index=data.get("feed_cost_index"), percentile=percentile,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        percentile = data.get("index_percentile")
        change = data.get("daily_change")
        if percentile is not None:
            return max(-1.0, min(1.0, (50 - percentile) / 50))
        if change is not None:
            return max(-1.0, min(1.0, -change * 15))
        return 0.0