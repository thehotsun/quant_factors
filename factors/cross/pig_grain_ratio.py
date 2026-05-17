"""
猪粮比因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：猪粮比 → 国家收储/抛储机制 → 猪价方向                                     │
│                                                                     │
│   猪粮比 < 5:1（一级预警）→ 养殖深度亏损 → 国家启动收储 → 猪价↑ → BUY 生猪       │
│     [逻辑：猪粮比跌破5:1触发一级预警，发改委启动中央冻猪肉收储，托底猪价]            │
│     [历史：2021年6月猪粮比跌破5:1，随后收储+产能去化，2022年4月猪价见底反弹]        │
│                                                                     │
│   猪粮比 5:1~5.5:1（二级预警）→ 关注收储 → 适度BUY                           │
│     [逻辑：二级预警意味着猪价接近底部区域，收储概率较高]                            │
│                                                                     │
│   猪粮比 > 9:1（价格过热）→ 国家启动抛储 → 猪价↓ → SELL 生猪                     │
│     [逻辑：猪粮比超过9:1触发价格过热预警，发改委投放储备肉，压制猪价]                 │
│                                                                     │
│   猪粮比 6:1~9:1（正常区间）→ 无信号                                       │
│                                                                     │
│ 公式：猪粮比 = 生猪价格(元/kg) / 玉米价格(元/kg)                                │
│ 数据：生猪期货(LH) + 玉米期货(C)                                             │
│                                                                     │
│ 注意：猪粮比是国家调控生猪市场的核心指标，发改委每周发布，具有政策信号意义              │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="pig_grain_ratio", category="cross",
    description="猪粮比 → 收储/抛储预期 → 生猪信号",
    asset="生猪期货(LH)", data_deps=["pork_futures", "corn_futures"]
)
class PigGrainRatio(BaseFactor):
    BASE_WARNING_LEVEL1 = 5.0
    BASE_WARNING_LEVEL2 = 5.5
    BASE_NORMAL_LOW = 6.0
    BASE_NORMAL_HIGH = 9.0

    def calculate(self) -> Dict[str, Any]:
        result = {
            "pig_grain_ratio": None, "pork_price": None,
            "corn_price": None, "warning_level": None,
        }

        pork_df = self.load("pork_futures")
        corn_df = self.load("corn_futures")
        if pork_df is None or corn_df is None:
            return result

        pork_price = self._safe_float(pork_df.tail(1), -1)
        corn_price = self._safe_float(corn_df.tail(1), -1)
        if pork_price is None or corn_price is None or corn_price == 0:
            return result

        ratio = pork_price / corn_price

        result["pork_price"] = pork_price
        result["corn_price"] = corn_price
        result["pig_grain_ratio"] = round(ratio, 2)

        if len(pork_df) >= 60 and len(corn_df) >= 60:
            merged = pd.merge(
                pork_df[['date', 'close']].rename(columns={'close': 'pork'}),
                corn_df[['date', 'close']].rename(columns={'close': 'corn'}),
                on='date', how='inner'
            )
            if len(merged) >= 20:
                merged['ratio'] = merged['pork'] / merged['corn']
                ratio_series = merged['ratio'].tail(60)
                result["ratio_ma20"] = round(float(ratio_series.tail(20).mean()), 2)
                result["ratio_percentile"] = round(self._percentile(ratio, ratio_series) * 100, 1)

                level1 = self._adaptive_threshold("pig_grain_level1", self.BASE_WARNING_LEVEL1, ratio_series, vol_sensitivity=20)
                level2 = self._adaptive_threshold("pig_grain_level2", self.BASE_WARNING_LEVEL2, ratio_series, vol_sensitivity=20)
                normal_high = self._adaptive_threshold("pig_grain_high", self.BASE_NORMAL_HIGH, ratio_series, vol_sensitivity=20)
                result["adaptive_level1"] = round(level1, 2)
                result["adaptive_level2"] = round(level2, 2)
                result["adaptive_normal_high"] = round(normal_high, 2)

                if ratio < level1:
                    result["warning_level"] = "一级预警"
                elif ratio < level2:
                    result["warning_level"] = "二级预警"
                elif ratio > normal_high:
                    result["warning_level"] = "价格过热"
                else:
                    result["warning_level"] = "正常"
        else:
            if ratio < self.BASE_WARNING_LEVEL1:
                result["warning_level"] = "一级预警"
            elif ratio < self.BASE_WARNING_LEVEL2:
                result["warning_level"] = "二级预警"
            elif ratio > self.BASE_NORMAL_HIGH:
                result["warning_level"] = "价格过热"
            else:
                result["warning_level"] = "正常"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("pig_grain_ratio")
        level = data.get("warning_level")
        if ratio is None:
            return None

        if level == "一级预警":
            return self._make_signal(
                asset="生猪期货(LH)", direction="BUY",
                reason=f"猪粮比{ratio:.1f}<5:1，一级预警→收储确定性高",
                holding_days=20, stop_loss=-0.05, confidence=0.75,
                strength=0.85, trigger="pig_grain_level1",
                pig_grain_ratio=ratio, warning_level=level,
            )
        if level == "二级预警":
            return self._make_signal(
                asset="生猪期货(LH)", direction="BUY",
                reason=f"猪粮比{ratio:.1f}<5.5:1，二级预警→关注收储",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.6, trigger="pig_grain_level2",
                pig_grain_ratio=ratio, warning_level=level,
            )
        if level == "价格过热":
            return self._make_signal(
                asset="生猪期货(LH)", direction="SELL",
                reason=f"猪粮比{ratio:.1f}>9:1，价格过热→抛储预期",
                holding_days=10, stop_loss=-0.03, confidence=0.65,
                strength=-0.7, trigger="pig_grain_overheat",
                pig_grain_ratio=ratio, warning_level=level,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio = data.get("pig_grain_ratio")
        if ratio is None:
            return 0.0
        level1 = data.get("adaptive_level1", self.BASE_WARNING_LEVEL1)
        level2 = data.get("adaptive_level2", self.BASE_WARNING_LEVEL2)
        normal_high = data.get("adaptive_normal_high", self.BASE_NORMAL_HIGH)
        if ratio < level1:
            return min(1.0, (level1 - ratio) / 2.0 + 0.5)
        if ratio < level2:
            return max(0.0, (level2 - ratio) / 2.0)
        if ratio > normal_high:
            return max(-1.0, -(ratio - normal_high) / 2.0)
        return 0.0