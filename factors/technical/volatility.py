"""
波动率因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：波动率锥 → 波动率回归 → 交易机会                                        │
│   短期波动率/长期波动率 > 2.0 → 极端高波动 → 恐慌过度 → 波动率将回归 → SELL         │
│     [逻辑：极端高波动不可持续，市场恐慌后波动率会回落，但回落方向不确定]                │
│   短期波动率/长期波动率 < 0.3 → 极端低波动 → 压抑过久 → 突破在即 → BUY             │
│     [逻辑：极端低波动后往往伴随大幅方向性突破，但方向不确定，需结合动量]                │
│                                                                     │
│ 链条2：波动率区间 → 仓位管理参考                                              │
│   高波动(ratio>1.5) → 宽止损、轻仓位                                          │
│   低波动(ratio<0.5) → 窄止损、可适度加仓                                        │
│   正常(0.8~1.2) → 标准仓位                                                  │
│                                                                     │
│ 适用品种：任意期货品种（通过symbol参数指定）                                       │
│ 注意：波动率因子本身不判断方向，主要用于风险管理和过滤动量信号                          │
│   - 高波动时动量信号置信度应打折                                                │
│   - 低波动时突破信号更可靠                                                     │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="volatility", category="technical",
    description="波动率因子：历史波动率 + 波动率锥 + 波动率回归信号",
    asset="通用(任意期货)", data_deps=[]
)
class VolatilityFactor(BaseFactor):
    SHORT_WINDOW = 5
    MID_WINDOW = 20
    LONG_WINDOW = 60

    def __init__(self, data_dir: str = "./data", adaptive: bool = True,
                 params: Dict[str, Any] = None, symbol: str = None, data_bus=None):
        super().__init__(data_dir, adaptive, params, data_bus=data_bus)
        self.symbol = symbol

    def calculate(self) -> Dict[str, Any]:
        result = {
            "vol_5d": None, "vol_20d": None, "vol_60d": None,
            "vol_ratio": None, "vol_regime": None,
        }

        if not self.symbol:
            return result

        df = self.load(self.symbol)
        if df is None or len(df) < self.LONG_WINDOW + 1:
            return result

        close = df['close'].astype(float)
        returns = close.pct_change().dropna()

        if len(returns) >= self.SHORT_WINDOW:
            result["vol_5d"] = round(float(returns.tail(self.SHORT_WINDOW).std()), 6)

        if len(returns) >= self.MID_WINDOW:
            result["vol_20d"] = round(float(returns.tail(self.MID_WINDOW).std()), 6)

        if len(returns) >= self.LONG_WINDOW:
            result["vol_60d"] = round(float(returns.tail(self.LONG_WINDOW).std()), 6)

        vol_short = result["vol_5d"]
        vol_long = result["vol_60d"]
        if vol_short and vol_long and vol_long > 0:
            result["vol_ratio"] = round(vol_short / vol_long, 2)

        ratio = result["vol_ratio"]
        if ratio is not None:
            if ratio > 1.5:
                result["vol_regime"] = "高波动"
            elif ratio > 1.2:
                result["vol_regime"] = "波动上升"
            elif ratio < 0.5:
                result["vol_regime"] = "低波动"
            elif ratio < 0.8:
                result["vol_regime"] = "波动下降"
            else:
                result["vol_regime"] = "正常"

        result["factor_value"] = result.get("vol_ratio")
        result["factor_value_type"] = "ratio" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        regime = data.get("vol_regime")
        ratio = data.get("vol_ratio")
        if regime is None:
            return None

        if regime == "高波动" and ratio and ratio > 2.0:
            return self._make_signal(
                asset=self.symbol, direction="HOLD",
                reason=f"波动率比{ratio:.1f}>2.0，极端高波动→波动率回归预期，方向不确定",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=0.0, trigger="vol_extreme_high",
                vol_regime=regime, vol_ratio=ratio,
            )

        if regime == "低波动" and ratio and ratio < 0.3:
            return self._make_signal(
                asset=self.symbol, direction="HOLD",
                reason=f"波动率比{ratio:.1f}<0.3，极端低波动→突破预期，方向不确定",
                holding_days=5, stop_loss=-0.02, confidence=0.45,
                strength=0.0, trigger="vol_extreme_low",
                vol_regime=regime, vol_ratio=ratio,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio = data.get("vol_ratio")
        if ratio is None:
            return 0.0
        if ratio > 1.5:
            return max(-1.0, -(ratio - 1.5) / 1.5)
        if ratio < 0.5:
            return min(1.0, (0.5 - ratio) / 0.5)
        return 0.0