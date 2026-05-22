"""
PMI→金属传导因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：PMI扩张 → 制造业需求 → 铜价（铜对PMI最敏感）                                 │
│   PMI>51 + PMI加速上升 + 铜涨幅<2% → 需求改善未定价 → 铜补涨 → BUY 铜              │
│     [逻辑：PMI是制造业需求的领先指标，铜是工业金属之王，PMI扩张直接拉动铜需求]           │
│                                                                     │
│ 链条2：PMI收缩 → 制造业需求萎缩 → 铜承压                                           │
│   PMI<49 + PMI加速下降 → 制造业收缩 → 铜需求下降 → SELL 铜                          │
│     [逻辑：PMI持续收缩意味着工厂减产、订单减少，铜的工业需求系统性下降]                 │
│                                                                     │
│ 链条3：PMI扩张 → 建筑+汽车需求 → 铝价                                             │
│   PMI>50 + PMI上升 → 建筑开工+汽车生产 → 铝需求增加 → BUY 铝                        │
│     [逻辑：铝的下游主要是建筑(30%)和汽车(20%)，PMI扩张意味着这两个行业需求改善]         │
│                                                                     │
│ PMI对金属的领先关系：                                                          │
│   PMI是月度数据，领先金属需求约1-2个月                                              │
│   铜对PMI最敏感（"铜博士"），铝次之，螺纹钢更看基建+地产                               │
│                                                                     │
│ 数据：PMI + 铜期货(CU) + 铝期货(AL)                                              │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof


@FactorRegistry.register(
    name="pmi_metals", category="cross/system",
    description="PMI→工业金属需求：PMI是铜/铝需求的领先指标",
    asset="铜期货(CU)", data_deps=["pmi", "copper_futures", "aluminum_futures"]
)
class PMIMetalsLink(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "pmi": None, "pmi_change": None, "expansion": None,
            "copper_price": None, "copper_change_20d": None,
            "aluminum_price": None, "aluminum_change_20d": None,
        }

        pmi_df = available_asof(self.load("pmi"), "pmi")
        copper_df = self.load("copper_futures")
        aluminum_df = self.load("aluminum_futures")

        if pmi_df is not None:
            col = None
            for candidate in ['value', 'pmi', '制造业-指数']:
                if candidate in pmi_df.columns:
                    col = candidate
                    break
            if col is not None and len(pmi_df) >= 2:
                current = self._safe_float(pmi_df.tail(1), -1, col=col)
                previous = self._safe_float(pmi_df.tail(2), -2, col=col)
                result["pmi"] = current
                result["pmi_change"] = round(current - previous, 2) if current and previous else None
                result["expansion"] = current > 50 if current else None

        if copper_df is not None:
            cp = self._safe_float(copper_df.tail(1), -1)
            result["copper_price"] = cp
            if len(copper_df) >= 20:
                cp20 = self._safe_float(copper_df.tail(20), -20)
                result["copper_change_20d"] = self._pct_change(cp, cp20)

        if aluminum_df is not None:
            ap = self._safe_float(aluminum_df.tail(1), -1)
            result["aluminum_price"] = ap
            if len(aluminum_df) >= 20:
                ap20 = self._safe_float(aluminum_df.tail(20), -20)
                result["aluminum_change_20d"] = self._pct_change(ap, ap20)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        pmi = data.get("pmi")
        pmi_change = data.get("pmi_change")
        copper_change = data.get("copper_change_20d")

        if pmi is None:
            return None

        regime = self._load_regime_data()

        if pmi > 51 and pmi_change is not None and pmi_change > 0.5 and copper_change is not None and copper_change < 0.02:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "industrial")
            return self._make_signal(
                asset="铜期货(CU)", direction="BUY",
                reason=f"PMI={pmi}加速扩张(+{pmi_change})但铜仅涨{copper_change*100:.1f}%，需求预期未充分定价→铜补涨",
                holding_days=15, stop_loss=-0.03, confidence=round(0.60 * regime_mult, 2),
                strength=0.60, trigger="pmi_copper_divergence",
                pmi=pmi, pmi_change=pmi_change, copper_change_20d=copper_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )

        if pmi < 49 and pmi_change is not None and pmi_change < -0.5:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "industrial")
            return self._make_signal(
                asset="铜期货(CU)", direction="SELL",
                reason=f"PMI={pmi}加速收缩({pmi_change})，制造业需求下降→铜承压",
                holding_days=10, stop_loss=-0.02, confidence=round(0.55 * regime_mult, 2),
                strength=-0.55, trigger="pmi_contraction_copper",
                pmi=pmi, pmi_change=pmi_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )

        if pmi > 50 and pmi_change is not None and pmi_change > 0:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "industrial")
            return self._make_signal(
                asset="铝期货(AL)", direction="BUY",
                reason=f"PMI={pmi}扩张中，建筑+汽车需求→铝受益",
                holding_days=10, stop_loss=-0.02, confidence=round(0.50 * regime_mult, 2),
                strength=0.50, trigger="pmi_expansion_aluminum",
                pmi=pmi, pmi_change=pmi_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        pmi = data.get("pmi")
        pmi_change = data.get("pmi_change")
        if pmi is None:
            return 0.0
        strength = (pmi - 50) / 5.0
        if pmi_change is not None:
            strength += pmi_change * 2
        return max(-1.0, min(1.0, strength))