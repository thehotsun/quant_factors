"""
猪鸡价差因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：猪鸡价比 → 替代效应 → 鸡肉需求                                        │
│   猪价/鸡价 > 2.5 → 猪肉太贵 → 消费者转向鸡肉 → 鸡肉需求↑ → BUY 鸡肉概念股       │
│   猪价/鸡价 < 1.5 → 猪肉便宜 → 鸡肉需求被压制 → SELL 鸡肉概念股                  │
│   [逻辑：猪肉和鸡肉是中国最主要的肉类蛋白来源，价格替代弹性显著]                    │
│                                                                     │
│ 链条2：鸡肉现货价格异动 → 短期供需                                           │
│   鸡肉现货单日涨>3% → 短期需求爆发或供给收缩 → BUY                              │
│                                                                     │
│ 数据状态：生猪期货(pork_futures) + 鸡肉现货(chicken_spot)                  │
│   chicken_spot 暂未接入：尚未找到稳定公开接口；禁止用网页 HTML 解析或替代口径冒充。 │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="pig_chicken_spread", category="cross",
    description="猪鸡价差→替代效应：猪贵→鸡肉替代需求↑→BUY鸡肉；猪贱→鸡肉被压制→SELL",
    asset="鸡肉概念(温氏/圣农/益生)", data_deps=["pork_futures", "chicken_spot"]
)
class PigChickenSpread(BaseFactor):
    SUBSTITUTION_THRESHOLD = 2.5
    REVERSE_THRESHOLD = 1.5

    def calculate(self) -> Dict[str, Any]:
        result = {
            "pig_chicken_ratio": None, "pork_price": None,
            "chicken_price": None, "chicken_daily_change": None,
        }

        pork_df = self.load("pork_futures")
        if pork_df is None:
            return result

        pork_price = self._safe_float(pork_df.tail(1), -1)
        result["pork_price"] = pork_price

        chicken_df = self.load("chicken_spot")

        if chicken_df is not None and len(chicken_df) >= 2:
            col = 'value' if 'value' in chicken_df.columns else 'close'
            chicken_price = self._safe_float(chicken_df.tail(1), -1, col=col)
            chicken_prev = self._safe_float(chicken_df.tail(2), -2, col=col)
            result["chicken_price"] = chicken_price
            result["chicken_daily_change"] = self._pct_change(chicken_price, chicken_prev)

            if pork_price and chicken_price and chicken_price > 0:
                result["pig_chicken_ratio"] = round(pork_price / chicken_price, 2)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("pig_chicken_ratio")
        chicken_change = data.get("chicken_daily_change")

        if ratio is not None and ratio > self.SUBSTITUTION_THRESHOLD:
            return self._make_signal(
                asset="鸡肉概念(温氏/圣农/益生)", direction="BUY",
                reason=f"猪鸡价比{ratio:.1f}>{self.SUBSTITUTION_THRESHOLD}→猪肉太贵→消费者转向鸡肉→替代需求增加→鸡肉股受益",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=min(1.0, (ratio - self.SUBSTITUTION_THRESHOLD) / 1.5),
                trigger="pig_chicken_substitution", pig_chicken_ratio=ratio,
            )

        if ratio is not None and ratio < self.REVERSE_THRESHOLD:
            return self._make_signal(
                asset="鸡肉概念(温氏/圣农/益生)", direction="SELL",
                reason=f"猪鸡价比{ratio:.1f}<{self.REVERSE_THRESHOLD}→猪肉便宜→鸡肉需求被压制→鸡肉股承压",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=-0.5, trigger="pig_cheap_pressure_chicken", pig_chicken_ratio=ratio,
            )

        if chicken_change is not None and chicken_change >= 0.03:
            return self._make_signal(
                asset="鸡肉概念(温氏/圣农/益生)", direction="BUY",
                reason=f"鸡肉现货单日涨{chicken_change*100:.1f}%→短期供给收缩或需求爆发→鸡肉股受益",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=0.50, trigger="chicken_spot_surge", daily_change=chicken_change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio = data.get("pig_chicken_ratio")
        if ratio is None:
            return 0.0
        if ratio > self.SUBSTITUTION_THRESHOLD:
            return min(1.0, (ratio - self.SUBSTITUTION_THRESHOLD) / 1.5)
        if ratio < self.REVERSE_THRESHOLD:
            return max(-1.0, -(self.REVERSE_THRESHOLD - ratio) / 1.0)
        return 0.0