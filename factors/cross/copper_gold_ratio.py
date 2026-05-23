"""
铜金比因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：铜金比 → 风险偏好 → 资产轮动                                              │
│                                                                     │
│   铜金比处于历史<10%分位 → 极端风险厌恶 → 避险资产受追捧 → BUY 黄金                │
│     [逻辑：铜金比极低意味着市场极度悲观，工业金属被抛售、避险资产被买入]                │
│     [历史：2008年金融危机、2020年COVID期间铜金比均暴跌至历史低位]                    │
│                                                                     │
│   铜金比Z-score<-2 → 风险偏好急剧下降 → BUY 黄金                                 │
│     [逻辑：铜金比快速下行意味着市场恐慌情绪蔓延]                                     │
│                                                                     │
│   铜金比处于历史>90%分位 → 极端风险偏好 → 经济过热 → BUY 沪深300                    │
│     [逻辑：铜金比极高意味着市场极度乐观，工业需求旺盛，权益资产受益]                    │
│                                                                     │
│ 铜金比的经济含义：                                                           │
│   铜 = 工业需求（经济晴雨表，"铜博士"）                                           │
│   金 = 避险需求（货币替代，恐慌指数）                                             │
│   铜金比↑ = 市场相信经济增长 > 担忧风险                                           │
│   铜金比↓ = 市场担忧风险 > 相信经济增长                                           │
│                                                                     │
│ 数据：铜期货(CU) + 黄金期货(AU)                                               │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="copper_gold_ratio", category="cross/system",
    description="铜金比 → 风险偏好指标 → 权益/商品信号",
    asset="沪深300ETF(510300)", data_deps=["copper_futures", "gold_futures"]
)
class CopperGoldRatio(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {"copper_gold_ratio": None, "copper_price": None, "gold_price": None}

        copper_df = self.load("copper_futures")
        gold_df = self.load("gold_futures")
        if copper_df is None or gold_df is None:
            return result

        copper_price = self._safe_float(copper_df.tail(1), -1)
        gold_price = self._safe_float(gold_df.tail(1), -1)
        if copper_price is None or gold_price is None or gold_price == 0:
            return result

        ratio = copper_price / gold_price
        result["copper_price"] = copper_price
        result["gold_price"] = gold_price
        result["copper_gold_ratio"] = round(ratio, 4)

        min_len = min(len(copper_df), len(gold_df))
        if min_len >= 60:
            merged = pd.merge(
                copper_df[['date', 'close']].rename(columns={'close': 'copper'}),
                gold_df[['date', 'close']].rename(columns={'close': 'gold'}),
                on='date', how='inner'
            )
            if len(merged) >= 20:
                merged['ratio'] = merged['copper'] / merged['gold']
                ratio_series = merged['ratio'].tail(60)
                result["ratio_ma20"] = round(float(ratio_series.tail(20).mean()), 4)
                result["ratio_percentile"] = round(self._percentile(ratio, ratio_series) * 100, 1)
                result["ratio_zscore"] = round(self._zscore(ratio, ratio_series), 2)

        result["factor_value"] = result.get("copper_gold_ratio")
        result["factor_value_type"] = "ratio" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("copper_gold_ratio")
        percentile = data.get("ratio_percentile")
        zscore = data.get("ratio_zscore")

        if ratio is None:
            return None

        if percentile is not None and percentile <= 10:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"铜金比={ratio:.4f}处于历史{percentile:.0f}%分位，极端风险厌恶→避险需求",
                holding_days=15, stop_loss=-0.03, confidence=0.65,
                strength=0.7, trigger="copper_gold_extreme_low",
                copper_gold_ratio=ratio, percentile=percentile,
            )

        if zscore is not None and zscore <= -2.0:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"铜金比Z-score={zscore:.1f}，风险偏好急剧下降",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="copper_gold_zscore_low", zscore=zscore,
            )

        if percentile is not None and percentile >= 90:
            return self._make_signal(
                asset="沪深300ETF(510300)", direction="BUY",
                reason=f"铜金比={ratio:.4f}处于历史{percentile:.0f}%分位，极端风险偏好→权益受益",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="copper_gold_extreme_high",
                copper_gold_ratio=ratio, percentile=percentile,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("ratio_zscore")
        if zscore is None:
            return 0.0
        return max(-1.0, min(1.0, zscore / 3.0))