"""
期限结构因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：近远月价差 → 现货供需格局 → 价格方向                                        │
│                                                                     │
│   近月>远月（Backwardation/现货升水）→ 现货紧缺 → 近月强势 → BUY 近月             │
│     [逻辑：Backwardation意味着当前现货供不应求，买方愿意为即时交割支付溢价]           │
│     [典型场景：铜矿罢工、原油地缘危机、农产品青黄不接]                               │
│                                                                     │
│   近月<远月（Contango/期货升水）→ 供应宽松 → 近月弱势 → SELL 近月                  │
│     [逻辑：Contango意味着当前供应充足，仓储成本+资金成本体现在远月升水中]              │
│     [典型场景：原油过剩、农产品丰收后]                                            │
│                                                                     │
│   极端Backwardation（价差分位>90%）→ 现货极度紧缺 → 强BUY                        │
│   极端Contango（价差分位<10%）→ 供应严重过剩 → 强SELL                             │
│                                                                     │
│ 适用品种：任意有近远月合约的期货品种（通过symbol+far_symbol参数指定）                   │
│ 注意：期限结构是商品期货最核心的定价因子之一，反映的是现货供需的真实状况                  │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="term_structure", category="technical",
    description="期限结构因子：近远月价差 → 供需格局判断",
    asset="通用(任意期货)", data_deps=[]
)
class TermStructureFactor(BaseFactor):
    def __init__(self, data_dir: str = "./data", adaptive: bool = True,
                 params: Dict[str, Any] = None, symbol: str = None,
                 far_symbol: str = None):
        super().__init__(data_dir, adaptive, params)
        self.symbol = symbol
        self.far_symbol = far_symbol

    def calculate(self) -> Dict[str, Any]:
        result = {
            "near_price": None, "far_price": None,
            "spread": None, "spread_pct": None, "structure": None,
        }

        if not self.symbol or not self.far_symbol:
            return result

        near_df = self.load(self.symbol)
        far_df = self.load(self.far_symbol)
        if near_df is None or far_df is None:
            return result

        near_price = self._safe_float(near_df.tail(1), -1)
        far_price = self._safe_float(far_df.tail(1), -1)
        if near_price is None or far_price is None:
            return result

        result["near_price"] = near_price
        result["far_price"] = far_price
        result["spread"] = round(near_price - far_price, 2)
        result["spread_pct"] = round((near_price - far_price) / far_price, 4) if far_price > 0 else None

        spread = result["spread"]
        if spread is not None:
            if spread > 0:
                result["structure"] = "BACKWARDATION"
            elif spread < 0:
                result["structure"] = "CONTANGO"
            else:
                result["structure"] = "FLAT"

        if len(near_df) >= 60 and len(far_df) >= 60:
            near_series = near_df['close'].astype(float)
            far_series = far_df['close'].astype(float)
            min_len = min(len(near_series), len(far_series))
            spreads = []
            for i in range(max(0, min_len - 60), min_len):
                spreads.append(float(near_series.iloc[i]) - float(far_series.iloc[i]))
            if spreads:
                spread_series = pd.Series(spreads)
                result["spread_ma20"] = round(float(spread_series.tail(20).mean()), 2)
                result["spread_percentile"] = round(self._percentile(spread, spread_series) * 100, 1)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        structure = data.get("structure")
        percentile = data.get("spread_percentile")
        if structure is None:
            return None

        if structure == "BACKWARDATION" and percentile is not None and percentile > 90:
            return self._make_signal(
                asset=self.symbol, direction="BUY",
                reason=f"极端Backwardation(分位{percentile:.0f}%)，现货紧缺→近月强势",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.65, trigger="extreme_backwardation",
                structure=structure, spread=data.get("spread"),
                spread_percentile=percentile,
            )

        if structure == "CONTANGO" and percentile is not None and percentile < 10:
            return self._make_signal(
                asset=self.symbol, direction="SELL",
                reason=f"极端Contango(分位{percentile:.0f}%)，供应过剩→近月弱势",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=-0.55, trigger="extreme_contango",
                structure=structure, spread=data.get("spread"),
                spread_percentile=percentile,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        structure = data.get("structure")
        percentile = data.get("spread_percentile")
        if structure == "BACKWARDATION" and percentile is not None:
            return min(1.0, percentile / 100)
        if structure == "CONTANGO" and percentile is not None:
            return max(-1.0, -(100 - percentile) / 100)
        return 0.0