"""
大豆压榨利润因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：压榨利润 → 油厂开工率 → 豆粕供给 → 豆粕价格                                  │
│                                                                     │
│   压榨利润 < -100元/吨（深度亏损）→ 油厂停机检修 → 豆粕供给收缩 → 豆粕↑ → BUY     │
│     [逻辑：油厂亏损时主动降低开工率，豆粕作为副产品供给减少，价格上升]                 │
│     [公式：压榨利润 = 豆油×0.18 + 豆粕×0.78 - 进口大豆 - 150元加工费]              │
│                                                                     │
│   压榨利润 > 300元/吨（高利润）→ 油厂满负荷生产 → 豆粕供给增加 → 豆粕↓ → SELL      │
│     [逻辑：高利润刺激油厂提高开工率，豆粕供给增加，价格承压]                          │
│                                                                     │
│   压榨利润 -100~300元/吨（正常区间）→ 无信号                                    │
│                                                                     │
│ 出率说明：                                                               │
│   - 1吨大豆 → 约0.18吨豆油 + 约0.78吨豆粕 + 约0.04吨损耗                        │
│   - 加工成本约150元/吨（含电力、人工、折旧）                                      │
│                                                                     │
│ 数据：豆油期货(Y) + 豆粕期货(M) + 进口大豆期货(B)                                 │
│                                                                     │
│ 局限性：                                                               │
│   - 用期货价格计算，忽略基差（期货vs现货差异）                                  │
│   - 未考虑副产品价格波动（如豆皮）                                            │
│   - 未考虑油厂库存周期（深亏时若库存高可能继续抛售）                              │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="crush_margin", category="cross",
    description="大豆压榨利润 → 豆粕供应预期",
    asset="豆粕期货(M)", data_deps=["soybean_oil_futures", "soybean_meal_futures", "soybean_import_futures"]
)
class CrushMargin(BaseFactor):
    OIL_YIELD = 0.18
    MEAL_YIELD = 0.78
    PROCESSING_COST = 150
    BASE_LOSS_THRESHOLD = -100
    BASE_PROFIT_THRESHOLD = 300

    def calculate(self) -> Dict[str, Any]:
        result = {
            "crush_margin": None, "soybean_oil_price": None,
            "soybean_meal_price": None, "import_soybean_price": None,
            "adaptive_loss_threshold": None, "adaptive_profit_threshold": None,
        }

        oil_df = self.load("soybean_oil_futures")
        meal_df = self.load("soybean_meal_futures")
        soybean_df = self.load("soybean_import_futures")
        if oil_df is None or meal_df is None or soybean_df is None:
            return result

        oil_price = self._safe_float(oil_df.tail(1), -1)
        meal_price = self._safe_float(meal_df.tail(1), -1)
        soybean_price = self._safe_float(soybean_df.tail(1), -1)
        if oil_price is None or meal_price is None or soybean_price is None:
            return result

        revenue = oil_price * self.OIL_YIELD + meal_price * self.MEAL_YIELD
        cost = soybean_price + self.PROCESSING_COST
        margin = revenue - cost

        result["soybean_oil_price"] = oil_price
        result["soybean_meal_price"] = meal_price
        result["import_soybean_price"] = soybean_price
        result["crush_margin"] = round(margin, 2)
        result["revenue_per_ton"] = round(revenue, 2)
        result["cost_per_ton"] = round(cost, 2)

        min_len = min(len(oil_df), len(meal_df), len(soybean_df))
        if min_len >= 60:
            merged = pd.merge(
                oil_df[['date', 'close']].rename(columns={'close': 'oil'}),
                meal_df[['date', 'close']].rename(columns={'close': 'meal'}),
                on='date', how='inner'
            )
            merged = pd.merge(
                merged,
                soybean_df[['date', 'close']].rename(columns={'close': 'soybean'}),
                on='date', how='inner'
            )
            if len(merged) >= 20:
                merged['margin'] = (merged['oil'] * self.OIL_YIELD +
                                    merged['meal'] * self.MEAL_YIELD -
                                    merged['soybean'] - self.PROCESSING_COST)
                margin_series = merged['margin'].tail(60)
                result["adaptive_loss_threshold"] = round(self._adaptive_threshold(
                    "crush_loss", abs(self.BASE_LOSS_THRESHOLD), margin_series.abs()
                ), 2)
                result["adaptive_profit_threshold"] = round(self._adaptive_threshold(
                    "crush_profit", self.BASE_PROFIT_THRESHOLD, margin_series.abs()
                ), 2)

        result["factor_value"] = result.get("crush_margin")
        result["factor_value_type"] = "spread" if result["factor_value"] is not None else None
        result["factor_direction"] = "higher_better"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        margin = data.get("crush_margin")
        loss_threshold = data.get("adaptive_loss_threshold", abs(self.BASE_LOSS_THRESHOLD))
        profit_threshold = data.get("adaptive_profit_threshold", self.BASE_PROFIT_THRESHOLD)
        if margin is None:
            return None

        if margin < -loss_threshold:
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"压榨利润{margin:.0f}元/吨< -{loss_threshold:.0f}，油厂停机→豆粕供应减少",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.65, trigger="crush_margin_negative", crush_margin=margin,
            )

        if margin > profit_threshold:
            return self._make_signal(
                asset="豆粕期货(M)", direction="SELL",
                reason=f"压榨利润{margin:.0f}元/吨>{profit_threshold:.0f}，油厂满负荷→豆粕供应增加",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=-0.55, trigger="crush_margin_high", crush_margin=margin,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        margin = data.get("crush_margin")
        loss_threshold = data.get("adaptive_loss_threshold", abs(self.BASE_LOSS_THRESHOLD))
        profit_threshold = data.get("adaptive_profit_threshold", self.BASE_PROFIT_THRESHOLD)
        if margin is None:
            return 0.0
        if margin < -loss_threshold:
            return min(1.0, abs(margin + loss_threshold) / (loss_threshold * 2))
        if margin > profit_threshold:
            return max(-1.0, -(margin - profit_threshold) / (profit_threshold * 2))
        return 0.0