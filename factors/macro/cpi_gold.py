"""
美国CPI→黄金因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：美国CPI偏离预期 → 实际利率预期 → 黄金ETF                                    │
│                                                                     │
│   CPI超预期≥0.2% → 通胀压力↑ → 美联储偏鹰 → 实际利率↑ → 黄金↓ → SELL            │
│   CPI低于预期≤-0.2% → 通胀压力↓ → 美联储偏鸽 → 实际利率↓ → 黄金↑ → BUY            │
│                                                                     │
│ 数据：AKShare macro_usa_cpi (美国CPI月度)                                   │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="cpi_gold", category="macro",
    description="美国CPI偏离预期→黄金ETF：CPI超预期利空黄金，低于预期利好黄金",
    asset="黄金ETF(518880)", data_deps=["us_cpi"]
)
class CpiGoldFactor(BaseFactor):

    def _cpi_expected(self):
        return self.params.get("cpi_expected", 0.3)

    def calculate(self) -> Dict[str, Any]:
        expected = self._cpi_expected()
        result = {
            "cpi_actual": None, "cpi_expected": expected,
            "diff": None,
        }

        df = self.load("us_cpi")
        if df is None or len(df) < 1:
            return result

        col = 'value' if 'value' in df.columns else ('今值' if '今值' in df.columns else df.columns[-1])
        actual = self._safe_float(df.tail(1), -1, col=col)
        if actual is None:
            return result

        result["cpi_actual"] = round(actual, 1)
        result["diff"] = round(actual - expected, 1)
        result["factor_value"] = result["diff"]
        result["factor_value_type"] = "spread"
        result["factor_direction"] = "two_sided"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        diff = data.get("diff")
        if diff is None:
            return None

        if diff >= 0.2:
            return self._make_signal(
                asset="黄金ETF(518880)", direction="SELL",
                reason=f"美国CPI超预期{diff:.1f}%→通胀压力→美联储偏鹰→实际利率上行→黄金承压",
                holding_days=15, stop_loss=-0.03, confidence=0.77,
                strength=-0.77, trigger="cpi_gold_above",
                cpi_actual=data["cpi_actual"], diff=diff,
            )

        if diff <= -0.2:
            return self._make_signal(
                asset="黄金ETF(518880)", direction="BUY",
                reason=f"美国CPI低于预期{abs(diff):.1f}%→通胀放缓→美联储偏鸽→实际利率下行→黄金受益",
                holding_days=15, stop_loss=-0.03, confidence=0.77,
                strength=0.77, trigger="cpi_gold_below",
                cpi_actual=data["cpi_actual"], diff=diff,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        diff = data.get("diff")
        if diff is None:
            return 0.0
        return max(-1.0, min(1.0, -diff * 3))