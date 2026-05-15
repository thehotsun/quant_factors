"""
布伦特原油→中国石油因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：布伦特原油单日异动 → 中国石油(601857)                                        │
│                                                                     │
│   布伦特原油单日涨≥5% → 能源板块受益 → BUY 中国石油                               │
│   布伦特原油单日跌≥5% → 能源板块承压 → SELL 中国石油                               │
│                                                                     │
│ 数据：AKShare energy_oil_hist (布伦特原油历史)                                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="oil_assets", category="energy",
    description="布伦特原油单日异动→中国石油：原油大涨利好能源股，大跌利空",
    asset="中国石油(601857)", data_deps=["brent_oil"]
)
class OilAssetsFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current": None, "previous": None,
            "daily_change": None,
        }

        df = self.load("brent_oil")
        if df is None or len(df) < 2:
            return result

        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        previous = self._safe_float(last_two, -2)
        change = self._pct_change(current, previous)

        result["current"] = current
        result["previous"] = previous
        result["daily_change"] = change

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        if change is None:
            return None

        if change >= 0.05:
            return self._make_signal(
                asset="中国石油(601857)", direction="BUY",
                reason=f"布伦特原油单日涨{change*100:.1f}%→能源板块受益→利好中国石油",
                holding_days=5, stop_loss=-0.02, confidence=0.57,
                strength=0.57, trigger="oil_surge_assets",
                daily_change=change,
            )

        if change <= -0.05:
            return self._make_signal(
                asset="中国石油(601857)", direction="SELL",
                reason=f"布伦特原油单日跌{abs(change)*100:.1f}%→能源板块承压→利空中国石油",
                holding_days=5, stop_loss=-0.02, confidence=0.57,
                strength=-0.57, trigger="oil_plunge_assets",
                daily_change=change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        if change is None:
            return 0.0
        return max(-1.0, min(1.0, change * 10))