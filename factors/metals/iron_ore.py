"""
铁矿石因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：铁矿石价格 → 螺纹钢成本（铁矿石占螺纹钢成本50%+）                           │
│   铁矿石↑ → 螺纹钢成本推升 → 钢厂挺价 → 螺纹钢↑ → BUY 螺纹钢                     │
│   铁矿石↓ → 螺纹钢成本下移 → 钢厂让利 → 螺纹钢↓ → SELL 螺纹钢                     │
│                                                                     │
│ 链条2：铁矿石库存 → 供给松紧                                                │
│   港口库存↓ → 铁矿石供给偏紧 → 铁矿石↑ → 螺纹钢成本↑                            │
│   港口库存↑ → 铁矿石供给宽松 → 铁矿石↓ → 螺纹钢成本↓                            │
│                                                                     │
│ 链条3：钢厂利润 = 螺纹钢 - 铁矿石×1.6 - 焦炭×0.5 - 800                         │
│   利润<0 → 钢厂减产 → 螺纹钢供给收缩 → 螺纹钢↑                                 │
│   利润>500 → 钢厂增产 → 螺纹钢供给增加 → 螺纹钢↓                               │
│                                                                     │
│ 数据：铁矿石期货(I) + 螺纹钢期货(RB)                                          │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="iron_ore", category="metals",
    description="铁矿石：螺纹钢成本核心驱动（占成本50%+）",
    asset="螺纹钢期货(RB)", data_deps=["iron_ore_futures", "rebar_futures"]
)
class IronOreFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "iron_ore_price": None,
            "iron_ore_change_5d": None,
            "iron_ore_zscore": None,
            "rebar_price": None,
            "steel_profit": None,
        }

        iron_df = self.load("iron_ore_futures")
        rebar_df = self.load("rebar_futures")

        if iron_df is not None and len(iron_df) >= 2:
            iron_current = self._safe_float(iron_df.tail(1), -1)
            result["iron_ore_price"] = iron_current

            if len(iron_df) >= 5:
                iron_5d_ago = self._safe_float(iron_df.iloc[-5], -1)
                result["iron_ore_change_5d"] = self._pct_change(iron_current, iron_5d_ago)

            if len(iron_df) >= 60:
                iron_series = iron_df['close'].astype(float)
                result["iron_ore_zscore"] = self._zscore(iron_current, iron_series.tail(60))
                result["iron_ore_percentile"] = round(self._percentile(iron_current, iron_series.tail(60)) * 100, 1)

        if rebar_df is not None and len(rebar_df) >= 1:
            result["rebar_price"] = self._safe_float(rebar_df.tail(1), -1)

        iron_p = result.get("iron_ore_price")
        rebar_p = result.get("rebar_price")
        if iron_p and rebar_p:
            result["steel_profit"] = round(rebar_p - iron_p * 1.6 - 800, 0)
            result["iron_cost_ratio"] = round(iron_p * 1.6 / rebar_p * 100, 1)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        iron_change = data.get("iron_ore_change_5d")
        iron_zscore = data.get("iron_ore_zscore")
        profit = data.get("steel_profit")

        if iron_change is not None and iron_change >= 0.05:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"铁矿石5日涨{iron_change*100:.1f}%→螺纹钢成本推升→钢厂挺价",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="iron_ore_surge",
                iron_ore_price=data["iron_ore_price"],
                iron_ore_change_5d=iron_change,
            )

        if iron_zscore is not None and iron_zscore > 2.0:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"铁矿石处于{iron_zscore:.1f}σ高位→成本端强支撑→螺纹钢偏强",
                holding_days=15, stop_loss=-0.04, confidence=0.65,
                strength=0.65, trigger="iron_ore_high_zscore",
                iron_ore_zscore=iron_zscore,
            )

        if profit is not None and profit < -200:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"钢厂利润{profit:.0f}元/吨→深度亏损→减产预期→螺纹钢供给收缩",
                holding_days=20, stop_loss=-0.05, confidence=0.70,
                strength=0.70, trigger="steel_loss_cut",
                steel_profit=profit,
            )

        if profit is not None and profit > 500:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="SELL",
                reason=f"钢厂利润{profit:.0f}元/吨→高利润→增产预期→螺纹钢供给增加",
                holding_days=15, stop_loss=-0.04, confidence=0.60,
                strength=-0.55, trigger="steel_high_profit",
                steel_profit=profit,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        iron_zscore = data.get("iron_ore_zscore")
        profit = data.get("steel_profit")
        if iron_zscore is not None and iron_zscore > 2.0:
            return min(1.0, iron_zscore / 3.0)
        if profit is not None and profit < -200:
            return min(1.0, abs(profit) / 500)
        if profit is not None and profit > 500:
            return max(-1.0, -profit / 500)
        return 0.0