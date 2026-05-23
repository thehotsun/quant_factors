"""
猪肉因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：生猪价格 → 养殖企业利润 → 养殖ETF                                    │
│   生猪期货价↑ → 养殖企业利润↑ → 养殖ETF(159865)股价↑ → BUY                  │
│   生猪期货价↓ → 养殖企业亏损 → 产能去化预期 → 远期猪价↑（需10个月兑现）         │
│                                                                     │
│ 链条2：能繁母猪存栏（领先10个月）→ 生猪出栏量 → 猪价                           │
│   能繁母猪存栏↓ → 10个月后出栏↓ → 供给收缩 → 猪价↑ → BUY 养殖ETF             │
│   能繁母猪存栏↑ → 10个月后出栏↑ → 供给过剩 → 猪价↓ → SELL 养殖ETF             │
│   [数据：农业农村部月度发布，AKShare暂不支持，预留接口]                          │
│                                                                     │
│ 链条3：猪周期位置判断（4年周期）                                            │
│   猪价<成本线 → 养殖亏损 → 散户退出 → 产能去化 → 12-14个月后猪价见顶            │
│   猪价>成本线×1.5 → 养殖暴利 → 散户涌入 → 产能扩张 → 10个月后猪价见底           │
│                                                                     │
│ 成本基准：牧原股份完全成本 ~12元/kg（2025年全年，行业最低）                      │
│   牧原2025年全年完全成本降至12元/kg（2024年为14元/kg），最好厂线10.5元/kg以下    │
│   行业平均成本~15元/kg（7.5元/斤为盈亏分界线）                                │
│   以牧原成本为基准判断行业盈亏：猪价<牧原成本→全行业亏损→产能去化确定性最高        │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="pork_etf", category="meat",
    description="生猪期货价格异动 → 养殖ETF套利：猪价涨→养殖利润改善→养殖ETF涨",
    asset="养殖ETF(159865)", data_deps=["pork_futures"]
)
class PorkFactor(BaseFactor):
    MUYUAN_COST = 12.0
    INDUSTRY_AVG_COST = 15.0

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "cycle_position": None,
        }

        df = self.load("pork_futures")
        if df is None or len(df) < 2:
            return result

        features = self._multi_window_features(df)
        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(df) >= 60:
            close = df['close'].astype(float)
            result["ma20"] = round(float(close.tail(20).mean()), 2)
            result["ma60"] = round(float(close.tail(60).mean()), 2)
            result["trend"] = "上涨" if result["ma20"] > result["ma60"] else "下跌"
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None

        if current:
            if current < self.MUYUAN_COST:
                result["cycle_position"] = "深度亏损→全行业亏损→产能去化中→远期看涨"
            elif current < self.INDUSTRY_AVG_COST:
                result["cycle_position"] = "亏损→牧原微利/行业亏损→关注去化"
            elif current > self.INDUSTRY_AVG_COST * 1.5:
                result["cycle_position"] = "暴利→全行业暴利→产能扩张中→远期看跌"
            elif current > self.MUYUAN_COST * 1.5:
                result["cycle_position"] = "盈利→牧原高利/行业盈利→关注补栏"
            else:
                result["cycle_position"] = "微利→牧原盈利/行业微利→正常"

        result["factor_value"] = result.get("zscore_20d")
        result["factor_value_type"] = "zscore" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        cycle = data.get("cycle_position")
        trend = data.get("trend")

        if zscore is not None and zscore <= -2.0 and cycle and "深度亏损" in str(cycle):
            return self._make_signal(
                asset="养殖ETF(159865)", direction="BUY",
                reason=f"猪价Z-score={zscore:.1f}，{cycle}→产能去化确定性高→远期猪价上涨→提前布局养殖股",
                holding_days=60, stop_loss=-0.08, confidence=0.75,
                strength=0.80, trigger="pork_cycle_bottom",
                zscore=zscore, cycle_position=cycle,
            )

        if change is not None and change >= 0.03 and trend == "上涨":
            return self._make_signal(
                asset="养殖ETF(159865)", direction="BUY",
                reason=f"生猪单日涨{change*100:.1f}%+趋势向上→养殖利润改善→养殖股受益",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="pork_price_surge",
                daily_change=change, trend=trend,
            )

        if zscore is not None and zscore > 2.0 and cycle and "暴利" in str(cycle):
            return self._make_signal(
                asset="养殖ETF(159865)", direction="SELL",
                reason=f"猪价Z-score={zscore:.1f}，{cycle}→产能扩张→远期猪价下跌→养殖股承压",
                holding_days=30, stop_loss=-0.05, confidence=0.65,
                strength=-0.65, trigger="pork_cycle_top",
                zscore=zscore, cycle_position=cycle,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        cycle = data.get("cycle_position")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if cycle and "深度亏损" in str(cycle):
            strength += 0.3
        elif cycle and "暴利" in str(cycle):
            strength -= 0.3
        return max(-1.0, min(1.0, strength))