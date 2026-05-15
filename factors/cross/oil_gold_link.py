"""
原油→黄金传导因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：油价上涨 → 通胀预期 → 黄金抗通胀需求                                       │
│   原油20日涨>10% + 黄金涨幅<原油涨幅 → 通胀预期未充分定价 → 黄金补涨 → BUY 黄金      │
│     [逻辑：油价是通胀的核心驱动因素，油价大涨后通胀预期上升，黄金作为抗通胀资产受益]      │
│                                                                     │
│ 链条2：油价暴跌 → 恐慌情绪 → 黄金避险需求                                        │
│   原油20日跌>15% → 市场恐慌 → 避险需求 → BUY 黄金                                 │
│     [逻辑：油价暴跌通常伴随经济衰退担忧或地缘危机，恐慌情绪推升黄金]                    │
│                                                                     │
│ 链条3：油金相关性 → 传导有效性确认                                              │
│   油金60日相关性>0.5 + 油价涨>5% → 通胀传导渠道畅通 → BUY 黄金                      │
│     [逻辑：高相关性意味着油价→金价的传导渠道有效，油价上涨会带动金价]                   │
│                                                                     │
│ 传导机制详解：                                                               │
│   原油↑ → 生产成本↑ → CPI↑ → 通胀预期↑ → 实际利率↓ → 黄金↑                        │
│   原油↓ → 通缩担忧 → 央行宽松 → 名义利率↓ → 实际利率↓ → 黄金↑（但路径不同）           │
│                                                                     │
│ 数据：原油期货(SC) + 黄金期货(AU)                                               │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="oil_gold_link", category="cross/system",
    description="原油→通胀预期→黄金：油价上涨推升通胀→黄金避险/抗通胀需求",
    asset="黄金期货(AU)", data_deps=["crude_oil_futures", "gold_futures"]
)
class OilGoldLink(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "oil_price": None, "gold_price": None,
            "oil_change_5d": None, "oil_change_20d": None,
            "gold_change_5d": None, "gold_change_20d": None,
            "oil_gold_corr_60d": None,
        }

        oil_df = self.load("crude_oil_futures")
        gold_df = self.load("gold_futures")
        if oil_df is None or gold_df is None:
            return result

        oil_price = self._safe_float(oil_df.tail(1), -1)
        gold_price = self._safe_float(gold_df.tail(1), -1)
        result["oil_price"] = oil_price
        result["gold_price"] = gold_price

        if len(oil_df) >= 5:
            oil_5d_ago = self._safe_float(oil_df.tail(5), -5)
            result["oil_change_5d"] = self._pct_change(oil_price, oil_5d_ago)
        if len(oil_df) >= 20:
            oil_20d_ago = self._safe_float(oil_df.tail(20), -20)
            result["oil_change_20d"] = self._pct_change(oil_price, oil_20d_ago)

        if len(gold_df) >= 5:
            gold_5d_ago = self._safe_float(gold_df.tail(5), -5)
            result["gold_change_5d"] = self._pct_change(gold_price, gold_5d_ago)
        if len(gold_df) >= 20:
            gold_20d_ago = self._safe_float(gold_df.tail(20), -20)
            result["gold_change_20d"] = self._pct_change(gold_price, gold_20d_ago)

        min_len = min(len(oil_df), len(gold_df))
        if min_len >= 60:
            oil_returns = oil_df['close'].astype(float).pct_change().dropna().tail(60)
            gold_returns = gold_df['close'].astype(float).pct_change().dropna().tail(60)
            common_len = min(len(oil_returns), len(gold_returns))
            if common_len >= 20:
                corr = oil_returns.tail(common_len).corr(gold_returns.tail(common_len))
                result["oil_gold_corr_60d"] = round(float(corr), 3)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        oil_change = data.get("oil_change_20d")
        gold_change = data.get("gold_change_20d")
        corr = data.get("oil_gold_corr_60d")

        if oil_change is None:
            return None

        if oil_change >= 0.10 and gold_change is not None and gold_change < oil_change:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"原油20日涨{oil_change*100:.1f}%但黄金仅涨{gold_change*100:.1f}%，通胀预期未充分定价→黄金补涨",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="oil_surge_gold_lag",
                oil_change_20d=oil_change, gold_change_20d=gold_change,
            )

        if oil_change <= -0.15:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"原油20日暴跌{oil_change*100:.1f}%，恐慌情绪→避险需求",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="oil_crash_gold_safe",
                oil_change_20d=oil_change,
            )

        if corr is not None and corr > 0.5 and oil_change >= 0.05:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"油金60日相关性{corr}，油价涨{oil_change*100:.1f}%→通胀传导→黄金受益",
                holding_days=10, stop_loss=-0.02, confidence=0.50,
                strength=0.50, trigger="oil_gold_corr_high",
                oil_change_20d=oil_change, oil_gold_corr=corr,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        oil_change = data.get("oil_change_20d")
        gold_change = data.get("gold_change_20d")
        if oil_change is None or gold_change is None:
            return 0.0
        divergence = oil_change - gold_change
        return max(-1.0, min(1.0, divergence * 5))