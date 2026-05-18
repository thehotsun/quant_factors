"""
大豆因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：进口大豆价格 → 豆粕成本 → 养殖利润                                     │
│   进口大豆(B)单日涨>3% → 压榨成本上升 → 豆粕涨价预期 → BUY 豆粕                 │
│   进口大豆(B)单日跌>3% → 压榨成本下降 → 饲料成本降低 → BUY 养殖ETF               │
│   [逻辑：中国大豆进口依赖度>80%，进口大豆价格直接决定豆粕成本]                     │
│                                                                     │
│ 链条2：CBOT大豆 × 汇率 → 进口成本指数                                        │
│   CBOT大豆↑ + 人民币贬值 → 进口成本双重推升 → 国内大豆/豆粕↑                     │
│   CBOT大豆↓ + 人民币升值 → 进口成本双重下降 → 国内大豆/豆粕↓                     │
│   [公式：进口成本指数 = CBOT大豆价 × USD/CNY汇率]                             │
│                                                                     │
│ 链条3：国产大豆(A) vs 进口大豆(B) 价差 → 替代效应                               │
│   进口大豆涨 → 国产大豆替代需求↑ → 国产大豆↑                                   │
│   [逻辑：国产大豆主要用于食品，进口大豆用于压榨，价差过大时存在替代]                 │
│                                                                     │
│ 数据：国产大豆期货(A) + 进口大豆期货(B) + CBOT大豆 + USD/CNY汇率                 │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="soybean", category="feed",
    description="进口大豆 + 国产大豆 + CBOT联动",
    asset="大豆期货(A/B)", data_deps=["soybean_domestic_futures", "soybean_import_futures", "cbot_soybean", "usd_cny"]
)
class SoybeanFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "domestic_soybean": None, "import_soybean": None,
            "domestic_change": None, "import_change": None,
        }

        dom_df = self.load("soybean_domestic_futures")
        if dom_df is not None and len(dom_df) >= 2:
            last_two = dom_df.tail(2)
            current = self._safe_float(last_two, -1)
            previous = self._safe_float(last_two, -2)
            result["domestic_soybean"] = current
            result["domestic_change"] = self._pct_change(current, previous)

        imp_df = self.load("soybean_import_futures")
        if imp_df is not None and len(imp_df) >= 2:
            last_two = imp_df.tail(2)
            current = self._safe_float(last_two, -1)
            previous = self._safe_float(last_two, -2)
            result["import_soybean"] = current
            result["import_change"] = self._pct_change(current, previous)

        cbot_df = self.load("cbot_soybean")
        if cbot_df is not None and len(cbot_df) >= 1:
            result["cbot_soybean"] = self._safe_float(cbot_df.tail(1), -1)

        forex_df = self.load("usd_cny")
        if forex_df is not None and len(forex_df) >= 1:
            col = 'close' if 'close' in forex_df.columns else ('DEXCHUS' if 'DEXCHUS' in forex_df.columns else 'value')
            result["usd_cny"] = self._safe_float(forex_df.tail(1), -1, col=col)

        cbot = result.get("cbot_soybean")
        fx = result.get("usd_cny")
        if cbot and fx:
            result["import_cost_index"] = round(cbot * fx, 2)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        import_change = data.get("import_change")
        change_threshold = self.params.get("change_threshold", 0.03)

        if import_change is not None and import_change >= change_threshold:
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"进口大豆单日上涨{import_change*100:.1f}%，豆粕成本推升预期",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=0.6, trigger="import_soybean_surge", import_change=import_change,
            )

        if import_change is not None and import_change <= -change_threshold:
            return self._make_signal(
                asset="养殖ETF(159865)", direction="BUY",
                reason=f"进口大豆下跌{abs(import_change)*100:.1f}%，饲料成本下降→养殖利润改善",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=0.5, trigger="import_soybean_drop", import_change=import_change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        change = data.get("import_change") or 0
        return max(-1.0, min(1.0, -change * 15))