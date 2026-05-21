"""
M2货币供应因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：M2增速 → 流动性环境 → 权益市场估值                                        │
│                                                                     │
│   M2增速>12% + 加速上行 → 流动性充裕 → 资金涌入股市 → BUY 沪深300                │
│     [逻辑：M2是股市流动性的领先指标，"M2-社融"剪刀差扩大意味着资金淤积在金融体系]      │
│     [历史：2020年M2增速从8%飙升至11%，随后A股迎来牛市]                            │
│                                                                     │
│   M2增速<8% + 加速下行 → 流动性收紧 → 股市"失血" → SELL 沪深300                  │
│     [逻辑：M2增速下行意味着央行收紧货币，股市增量资金减少]                           │
│                                                                     │
│   M2增速 8~12% → 中性，关注趋势变化                                           │
│                                                                     │
│ 注意：M2是月度数据，信号频率低但确定性高，适合中期仓位判断                             │
│   - M2拐点领先股市拐点约1-3个月                                               │
│   - 需结合社融数据判断资金是否进入实体经济（"M2-社融"剪刀差）                         │
│                                                                     │
│ 数据：中国M2货币供应量(ak.macro_china_money_supply)                           │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof, latest_period_date, latest_release_date


@FactorRegistry.register(
    name="money_supply", category="macro",
    description="M2增速 → 流动性环境 → 权益市场信号",
    asset="沪深300ETF(510300)", data_deps=["m2"]
)
class MoneySupplyFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "m2_yoy": None, "m2_change": None, "trend": None,
            "factor_value": None,
            "period_date": None,
            "release_date": None,
        }

        df = available_asof(self.load("m2"), "m2", self.params.get("as_of"))
        if df is None:
            return result

        col = None
        for candidate in ['value', 'm2', 'M2', '货币和准货币(M2)-同比增长']:
            if candidate in df.columns:
                col = candidate
                break
        if col is None:
            for c in df.columns:
                if 'M2' in str(c) or 'm2' in str(c).lower() or '货币' in str(c):
                    col = c
                    break
        if col is None:
            return result
        if len(df) >= 2:
            result["period_date"] = latest_period_date(df)
            result["release_date"] = latest_release_date(df)
            current = self._safe_float(df.tail(1), -1, col=col)
            previous = self._safe_float(df.tail(2), -2, col=col)
            result["m2_yoy"] = current
            result["factor_value"] = current
            result["m2_change"] = round(current - previous, 2) if current and previous else None

        if len(df) >= 6:
            recent = df.tail(6)
            vals = recent[col].astype(float).dropna().tolist()
            if len(vals) >= 3:
                if vals[-1] > vals[-2] > vals[-3]:
                    result["trend"] = "加速上行"
                elif vals[-1] < vals[-2] < vals[-3]:
                    result["trend"] = "加速下行"
                elif vals[-1] > vals[-2]:
                    result["trend"] = "温和上行"
                elif vals[-1] < vals[-2]:
                    result["trend"] = "温和下行"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        m2 = data.get("m2_yoy")
        trend = data.get("trend")
        if m2 is None:
            return None

        if m2 > 12 and trend == "加速上行":
            return self._make_signal(
                asset="沪深300ETF(510300)", direction="BUY",
                reason=f"M2增速{m2}%>12%且加速上行，流动性充裕→权益受益",
                holding_days=20, stop_loss=-0.03, confidence=0.65,
                strength=0.7, trigger="m2_surge", m2_yoy=m2, trend=trend,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=m2,
            )

        if m2 < 8 and trend == "加速下行":
            return self._make_signal(
                asset="沪深300ETF(510300)", direction="SELL",
                reason=f"M2增速{m2}%<8%且加速下行，流动性收紧→权益承压",
                holding_days=15, stop_loss=-0.03, confidence=0.60,
                strength=-0.6, trigger="m2_tight", m2_yoy=m2, trend=trend,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=m2,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        m2 = data.get("m2_yoy")
        if m2 is None:
            return 0.0
        return max(-1.0, min(1.0, (m2 - 9) / 4.0))