"""
菜粕因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：豆粕/菜粕比 → 蛋白替代 → 菜粕需求                                       │
│   豆粕/菜粕比 > 1.3 → 豆粕太贵 → 饲料厂增加菜粕配比 → 菜粕需求↑ → BUY 菜粕       │
│   [逻辑：豆粕和菜粕都是饲料蛋白来源，配方中可互相替代，价差过大会触发替代]            │
│                                                                     │
│ 链条2：菜粕自身价格异动 → 短期供需                                           │
│   菜粕价格极端低位 → 性价比突出 → 需求回升 → BUY                                │
│                                                                     │
│ 替代关系详解：                                                           │
│   - 豆粕蛋白含量~43%，菜粕蛋白含量~36%                                       │
│   - 当豆粕/菜粕比>1.3时，菜粕单位蛋白成本更低，饲料厂倾向多用菜粕                    │
│   - 菜粕含硫苷等抗营养因子，添加比例有上限（通常<15%）                             │
│                                                                     │
│ 数据：菜粕期货(RM) + 豆粕期货(M)                                            │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="rapeseed_meal", category="feed",
    description="菜粕期货 + 豆菜粕价差替代",
    asset="菜粕期货(RM)", data_deps=["rapeseed_meal_futures", "soybean_meal_futures"]
)
class RapeseedMealFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "yesterday_price": None,
            "daily_change": None, "meal_rapeseed_spread": None,
            "meal_rapeseed_ratio": None,
        }

        rm_df = self.load("rapeseed_meal_futures")
        sm_df = self.load("soybean_meal_futures")

        if rm_df is None or len(rm_df) < 2:
            return result

        features = self._multi_window_features(rm_df)
        last_two = rm_df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["yesterday_price"] = yesterday
        result["daily_change"] = change
        result.update(features)

        if sm_df is not None and current:
            meal_price = self._safe_float(sm_df.tail(1), -1)
            if meal_price:
                result["meal_rapeseed_spread"] = round(meal_price - current, 2)
                result["meal_rapeseed_ratio"] = round(meal_price / current, 2) if current > 0 else None

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("meal_rapeseed_ratio")

        if ratio is not None and ratio > 1.3:
            return self._make_signal(
                asset="菜粕期货(RM)", direction="BUY",
                reason=f"豆粕/菜粕比{ratio:.1f}>1.3，菜粕性价比突出→替代需求增加",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=0.5, trigger="meal_rapeseed_substitution",
                spread=data.get("meal_rapeseed_spread"), ratio=ratio,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio = data.get("meal_rapeseed_ratio")
        if ratio is None:
            return 0.0
        if ratio > 1.3:
            return min(1.0, (ratio - 1.3) / 0.5)
        return 0.0