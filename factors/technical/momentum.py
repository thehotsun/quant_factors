"""
动量因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：多周期动量共振 → 趋势确认                                             │
│   5日动量>0 + 20日动量>0 + 60日动量>0 → 三周期共振向上 → BUY                    │
│   5日动量<0 + 20日动量<0 + 60日动量<0 → 三周期共振向下 → SELL                    │
│   [逻辑：多周期共振意味着趋势强度高、方向一致，假突破概率低]                          │
│                                                                     │
│ 链条2：动量加速/衰减 → 趋势拐点预警                                            │
│   短期动量 > 中期动量 → 动量加速 → 趋势加强 → 顺势而为                            │
│   短期动量 < 中期动量 → 动量衰减 → 趋势减弱 → 警惕反转                            │
│   [逻辑：动量加速意味着趋势在加强，动量衰减意味着趋势可能即将结束]                      │
│                                                                     │
│ 综合得分：加权平均（短期30% + 中期40% + 加速30%），tanh归一化到[-1,1]               │
│                                                                     │
│ 适用品种：任意期货品种（通过symbol参数指定）                                       │
│ 注意：动量因子在趋势市中表现好，震荡市中容易反复打脸，需结合波动率因子过滤                │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="momentum", category="technical",
    description="多周期动量因子：短期/中期/长期动量 + 动量加速/衰减",
    asset="通用(任意期货)", data_deps=[]
)
class MomentumFactor(BaseFactor):
    SHORT_WINDOW = 5
    MID_WINDOW = 20
    LONG_WINDOW = 60

    def __init__(self, data_dir: str = "./data", adaptive: bool = True,
                 params: Dict[str, Any] = None, symbol: str = None):
        super().__init__(data_dir, adaptive, params)
        self.symbol = symbol

    def calculate(self) -> Dict[str, Any]:
        result = {
            "momentum_5d": None, "momentum_20d": None, "momentum_60d": None,
            "momentum_acceleration": None, "momentum_score": None,
            "volatility_20d": None, "volatility_regime": None,
        }

        if not self.symbol:
            return result

        df = self.load(self.symbol)
        if df is None or len(df) < self.LONG_WINDOW:
            return result

        close = df['close'].astype(float)
        current = float(close.iloc[-1])

        if len(close) >= self.SHORT_WINDOW + 1:
            result["momentum_5d"] = round(float(close.iloc[-1] / close.iloc[-self.SHORT_WINDOW - 1] - 1), 4)

        if len(close) >= self.MID_WINDOW + 1:
            result["momentum_20d"] = round(float(close.iloc[-1] / close.iloc[-self.MID_WINDOW - 1] - 1), 4)

        if len(close) >= self.LONG_WINDOW + 1:
            result["momentum_60d"] = round(float(close.iloc[-1] / close.iloc[-self.LONG_WINDOW - 1] - 1), 4)

        m5 = result["momentum_5d"]
        m20 = result["momentum_20d"]
        if m5 is not None and m20 is not None:
            result["momentum_acceleration"] = round(m5 - m20, 4)

        if len(close) >= 60:
            returns = close.pct_change().dropna()
            vol_20d = float(returns.tail(20).std())
            vol_60d = float(returns.tail(60).std())
            result["volatility_20d"] = round(vol_20d, 6)
            if vol_60d > 0:
                vol_ratio = vol_20d / vol_60d
                result["volatility_ratio"] = round(vol_ratio, 4)
                if vol_ratio < 0.7:
                    result["volatility_regime"] = "低波动→趋势市→动量信号可靠"
                elif vol_ratio > 1.5:
                    result["volatility_regime"] = "高波动→震荡市→动量信号打折"
                else:
                    result["volatility_regime"] = "正常波动→动量信号正常"

        scores = []
        weights = []
        if m5 is not None:
            scores.append(np.tanh(m5 * 30))
            weights.append(0.3)
        if m20 is not None:
            scores.append(np.tanh(m20 * 15))
            weights.append(0.4)
        if result["momentum_acceleration"] is not None:
            scores.append(np.tanh(result["momentum_acceleration"] * 50))
            weights.append(0.3)

        if scores:
            result["momentum_score"] = round(float(np.average(scores, weights=weights)), 4)

        result["factor_value"] = result.get("momentum_score")
        result["factor_value_type"] = "score" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        score = data.get("momentum_score")
        vol_regime = data.get("volatility_regime", "")
        if score is None:
            return None

        confidence = 0.55
        if "低波动" in str(vol_regime):
            confidence = 0.65
        elif "高波动" in str(vol_regime):
            confidence = 0.40

        if score > 0.5:
            strength = max(-1.0, min(1.0, score * confidence / 0.55))
            return self._make_signal(
                asset=self.symbol, direction="BUY",
                reason=f"动量得分{score:.2f}>0.5，多周期共振向上（{vol_regime}）",
                holding_days=10, stop_loss=-0.03, confidence=confidence,
                strength=strength, trigger="momentum_strong",
                momentum_5d=data.get("momentum_5d"),
                momentum_20d=data.get("momentum_20d"),
                momentum_score=score, volatility_regime=vol_regime,
            )

        if score < -0.5:
            strength = max(-1.0, min(1.0, score * confidence / 0.55))
            return self._make_signal(
                asset=self.symbol, direction="SELL",
                reason=f"动量得分{score:.2f}<-0.5，多周期共振向下（{vol_regime}）",
                holding_days=10, stop_loss=-0.03, confidence=confidence,
                strength=strength, trigger="momentum_weak",
                momentum_5d=data.get("momentum_5d"),
                momentum_20d=data.get("momentum_20d"),
                momentum_score=score, volatility_regime=vol_regime,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        score = data.get("momentum_score")
        vol_regime = data.get("volatility_regime", "")
        if score is None:
            return 0.0
        if "低波动" in str(vol_regime):
            return max(-1.0, min(1.0, score * 1.2))
        if "高波动" in str(vol_regime):
            return max(-1.0, min(1.0, score * 0.7))
        return score