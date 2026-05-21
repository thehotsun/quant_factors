"""
PMI因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：PMI方向变化 → 经济周期位置 → 股市风格轮动                              │
│                                                                     │
│   PMI连续2个月↑ + PMI>50 → 经济扩张确认 → BUY 顺周期（沪深300/工业金属）       │
│     [逻辑：PMI是股市盈利的领先指标，扩张期企业盈利改善]                         │
│                                                                     │
│   PMI连续2个月↓ + PMI<50 → 经济收缩确认 → 减仓顺周期 → 转向防御               │
│     [注意：PMI收缩≠股市必跌，政策宽松可能对冲，因此仅减仓而非做空]               │
│                                                                     │
│   PMI>50但PMI↓ → 扩张减速 → 谨慎，降低仓位                                │
│   PMI<50但PMI↑ → 收缩收窄 → 关注拐点，可能即将复苏                           │
│                                                                     │
│ 数据：国家统计局月度发布（每月最后一天），AKShare: ak.macro_china_pmi          │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof, latest_period_date, latest_release_date


@FactorRegistry.register(
    name="pmi", category="macro",
    description="PMI方向变化→经济周期判断：连续2月↑+>50→BUY顺周期；连续2月↓+<50→减仓",
    asset="沪深300(000300)", data_deps=["pmi"]
)
class PMIFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_pmi": None, "prev_pmi": None,
            "pmi_change": None, "pmi_direction": None,
            "consecutive_up": 0, "consecutive_down": 0,
            "cycle_phase": None,
            "factor_value": None,
            "period_date": None,
            "release_date": None,
        }

        df = available_asof(self.load("pmi"), "pmi", self.params.get("as_of"))
        if df is None or len(df) < 3:
            return result

        col = 'value' if 'value' in df.columns else 'pmi'
        if col not in df.columns:
            for candidate in ['制造业-指数', '制造业PMI']:
                if candidate in df.columns:
                    col = candidate
                    break
        if col not in df.columns:
            return result

        result["period_date"] = latest_period_date(df)
        result["release_date"] = latest_release_date(df)

        recent = df.tail(6)
        values = recent[col].astype(float).values

        result["current_pmi"] = round(float(values[-1]), 1)
        result["prev_pmi"] = round(float(values[-2]), 1)
        result["factor_value"] = result["current_pmi"]
        result["pmi_change"] = round(result["current_pmi"] - result["prev_pmi"], 1)

        if result["pmi_change"] > 0:
            result["pmi_direction"] = "上升"
        elif result["pmi_change"] < 0:
            result["pmi_direction"] = "下降"
        else:
            result["pmi_direction"] = "持平"

        up_count = 0
        down_count = 0
        for i in range(1, len(values)):
            if values[i] > values[i - 1]:
                up_count += 1
                down_count = 0
            elif values[i] < values[i - 1]:
                down_count += 1
                up_count = 0
        result["consecutive_up"] = up_count
        result["consecutive_down"] = down_count

        current = result["current_pmi"]
        if current >= 50 and up_count >= 2:
            result["cycle_phase"] = "扩张确认→顺周期受益"
        elif current >= 50 and down_count >= 2:
            result["cycle_phase"] = "扩张减速→谨慎"
        elif current < 50 and up_count >= 2:
            result["cycle_phase"] = "收缩收窄→关注拐点"
        elif current < 50 and down_count >= 2:
            result["cycle_phase"] = "收缩确认→防御为主"
        elif current >= 50:
            result["cycle_phase"] = "扩张中→中性偏多"
        else:
            result["cycle_phase"] = "收缩中→中性偏空"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        phase = data.get("cycle_phase")
        pmi = data.get("current_pmi")
        consecutive_up = data.get("consecutive_up", 0)
        consecutive_down = data.get("consecutive_down", 0)

        if phase == "扩张确认→顺周期受益":
            return self._make_signal(
                asset="沪深300(000300)", direction="BUY",
                reason=f"PMI={pmi}，连续{consecutive_up}月上升→经济扩张确认→企业盈利改善→顺周期受益",
                holding_days=30, stop_loss=-0.05, confidence=0.65,
                strength=0.65, trigger="pmi_expansion_confirmed",
                pmi=pmi, consecutive_up=consecutive_up, cycle_phase=phase,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=pmi,
            )

        if phase == "收缩收窄→关注拐点":
            return self._make_signal(
                asset="沪深300(000300)", direction="BUY",
                reason=f"PMI={pmi}<50但连续{consecutive_up}月上升→收缩收窄→经济可能触底→左侧布局",
                holding_days=30, stop_loss=-0.05, confidence=0.50,
                strength=0.50, trigger="pmi_contraction_narrowing",
                pmi=pmi, consecutive_up=consecutive_up, cycle_phase=phase,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=pmi,
            )

        if phase == "收缩确认→防御为主":
            return self._make_signal(
                asset="沪深300(000300)", direction="SELL",
                reason=f"PMI={pmi}<50，连续{consecutive_down}月下降→经济收缩确认→减仓顺周期→转向防御",
                holding_days=30, stop_loss=-0.03, confidence=0.55,
                strength=-0.55, trigger="pmi_contraction_confirmed",
                pmi=pmi, consecutive_down=consecutive_down, cycle_phase=phase,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=pmi,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        pmi = data.get("current_pmi")
        consecutive_up = data.get("consecutive_up", 0)
        consecutive_down = data.get("consecutive_down", 0)
        if pmi is None:
            return 0.0
        strength = (pmi - 50) / 5.0
        if consecutive_up >= 2:
            strength += 0.2
        if consecutive_down >= 2:
            strength -= 0.2
        return max(-1.0, min(1.0, strength))