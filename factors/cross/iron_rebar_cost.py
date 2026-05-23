"""
铁矿石→螺纹钢成本传导因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：铁矿石(I) → 螺纹钢成本 → 螺纹钢(RB)价格                                  │
│                                                                     │
│   铁矿石占螺纹钢成本50%+，是螺纹钢最重要的成本驱动因子                            │
│                                                                     │
│   铁矿石↑ + 螺纹钢未跟涨 → 钢厂利润压缩 → 减产预期 → 螺纹钢补涨 → BUY 螺纹钢       │
│   铁矿石↓ + 螺纹钢未跟跌 → 钢厂利润扩大 → 增产预期 → 螺纹钢补跌 → SELL 螺纹钢       │
│                                                                     │
│   铁矿石/螺纹钢比值 → 成本传导效率                                          │
│   比值↑ → 铁矿石相对螺纹钢偏强 → 成本推升 → BUY 螺纹钢                           │
│   比值↓ → 铁矿石相对螺纹钢偏弱 → 成本下移 → SELL 螺纹钢                          │
│                                                                     │
│ 数据：铁矿石期货(I) + 螺纹钢期货(RB)                                          │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="iron_rebar_cost", category="cross/system",
    description="铁矿石→螺纹钢成本传导：铁矿石涨→钢厂成本推升→螺纹钢补涨",
    asset="螺纹钢期货(RB)", data_deps=["iron_ore_futures", "rebar_futures"]
)
class IronRebarCostLink(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "iron_ore_price": None,
            "rebar_price": None,
            "iron_rebar_ratio": None,
            "ratio_zscore": None,
            "steel_profit": None,
            "cost_push_signal": None,
        }

        iron_df = self.load("iron_ore_futures")
        rebar_df = self.load("rebar_futures")

        if iron_df is None or rebar_df is None:
            return result

        iron_current = self._safe_float(iron_df.tail(1), -1)
        rebar_current = self._safe_float(rebar_df.tail(1), -1)
        if iron_current is None or rebar_current is None or rebar_current == 0:
            return result

        result["iron_ore_price"] = iron_current
        result["rebar_price"] = rebar_current
        result["iron_rebar_ratio"] = round(iron_current / rebar_current, 4)

        result["steel_profit"] = round(rebar_current - iron_current * 1.6 - 800, 0)

        if len(iron_df) >= 60 and len(rebar_df) >= 60:
            merged = pd.merge(
                iron_df[['date', 'close']].rename(columns={'close': 'iron'}),
                rebar_df[['date', 'close']].rename(columns={'close': 'rebar'}),
                on='date', how='inner'
            )
            if len(merged) >= 20:
                merged['ratio'] = merged['iron'] / merged['rebar']
                ratio_series = merged['ratio'].tail(60)
                result["ratio_zscore"] = self._zscore(result["iron_rebar_ratio"], ratio_series)
                result["ratio_percentile"] = round(self._percentile(result["iron_rebar_ratio"], ratio_series) * 100, 1)

        iron_change_5d = None
        rebar_change_5d = None
        if len(iron_df) >= 5 and len(rebar_df) >= 5:
            iron_5d = self._safe_float(iron_df.tail(5), -5)
            rebar_5d = self._safe_float(rebar_df.tail(5), -5)
            iron_change_5d = self._pct_change(iron_current, iron_5d)
            rebar_change_5d = self._pct_change(rebar_current, rebar_5d)
            result["iron_change_5d"] = iron_change_5d
            result["rebar_change_5d"] = rebar_change_5d

        if iron_change_5d is not None and rebar_change_5d is not None:
            divergence = iron_change_5d - rebar_change_5d
            result["divergence"] = round(divergence * 100, 1)
            if divergence > 0.03:
                result["cost_push_signal"] = "铁矿石领涨→螺纹钢成本推升→螺纹钢补涨预期"
            elif divergence < -0.03:
                result["cost_push_signal"] = "铁矿石领跌→螺纹钢成本下移→螺纹钢补跌预期"
            else:
                result["cost_push_signal"] = "铁矿石与螺纹钢同步→成本传导正常"

        result["factor_value"] = result.get("iron_rebar_ratio")
        result["factor_value_type"] = "ratio" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio_z = data.get("ratio_zscore")
        divergence = data.get("divergence")
        profit = data.get("steel_profit")

        if ratio_z is not None and ratio_z > 2.0 and profit is not None and profit < 200:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"铁矿/螺纹比{ratio_z:.1f}σ高位+钢厂利润{profit:.0f}→成本推升+利润压缩→螺纹钢补涨",
                holding_days=15, stop_loss=-0.04, confidence=0.70,
                strength=0.70, trigger="iron_rebar_cost_push",
                iron_rebar_ratio=data["iron_rebar_ratio"],
                ratio_zscore=ratio_z, steel_profit=profit,
            )

        if divergence is not None and divergence > 5 and profit is not None and profit < 0:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"铁矿石5日领先螺纹钢{divergence:.0f}%+钢厂亏损→成本推升→螺纹钢补涨",
                holding_days=10, stop_loss=-0.03, confidence=0.65,
                strength=0.65, trigger="iron_lead_rebar",
                divergence=divergence, steel_profit=profit,
            )

        if ratio_z is not None and ratio_z < -2.0 and profit is not None and profit > 400:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="SELL",
                reason=f"铁矿/螺纹比{ratio_z:.1f}σ低位+钢厂高利润{profit:.0f}→成本下移+增产→螺纹钢补跌",
                holding_days=15, stop_loss=-0.04, confidence=0.65,
                strength=-0.65, trigger="iron_rebar_cost_drop",
                iron_rebar_ratio=data["iron_rebar_ratio"],
                ratio_zscore=ratio_z, steel_profit=profit,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio_z = data.get("ratio_zscore")
        profit = data.get("steel_profit")
        if ratio_z is not None and ratio_z > 2.0 and profit is not None and profit < 200:
            return min(1.0, ratio_z / 3.0)
        if ratio_z is not None and ratio_z < -2.0 and profit is not None and profit > 400:
            return max(-1.0, ratio_z / 3.0)
        return 0.0