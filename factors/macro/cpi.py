"""
CPI因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：CPI水平 → 通胀环境 → 消费板块/货币政策预期                              │
│                                                                     │
│   CPI 0~2%（温和通胀）→ 企业有定价权 → 消费板块受益 → BUY                    │
│     [逻辑：温和通胀意味着需求健康，企业可以传导成本，利润率稳定]                  │
│                                                                     │
│   CPI 2~3%（正常偏高）→ 中性，关注是否加速                                  │
│                                                                     │
│   CPI >5%（恶性通胀）→ 购买力侵蚀 + 紧缩预期 → SELL 消费                     │
│     [逻辑：高通胀→央行加息→融资成本↑→消费信贷收缩→可选消费承压]                 │
│                                                                     │
│   CPI <0（通缩）→ 需求不足 → 企业降价去库存 → 利润压缩 → SELL 消费             │
│     [逻辑：通缩环境下消费者推迟购买，企业收入下降]                              │
│                                                                     │
│ 数据：国家统计局月度发布，AKShare: ak.macro_china_cpi                      │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof, latest_period_date, latest_release_date


@FactorRegistry.register(
    name="cpi", category="macro",
    description="CPI通胀环境→消费板块：温和通胀(0~2%)利好消费；恶性通胀(>5%)或通缩(<0)利空",
    asset="消费ETF(159928)", data_deps=["cpi"]
)
class CPIFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_cpi": None, "prev_cpi": None,
            "cpi_change": None, "cpi_trend": None,
            "inflation_regime": None,
            "factor_value": None,
            "period_date": None,
            "release_date": None,
        }

        df = available_asof(self.load("cpi"), "cpi", self.params.get("as_of"))
        if df is None or len(df) < 3:
            return result

        col = 'value' if 'value' in df.columns else 'cpi'
        if col not in df.columns:
            for candidate in ['全国-同比增长', '全国-当月']:
                if candidate in df.columns:
                    col = candidate
                    break
        if col not in df.columns:
            return result

        result["period_date"] = latest_period_date(df)
        result["release_date"] = latest_release_date(df)

        recent = df.tail(6)
        values = recent[col].astype(float).values

        result["current_cpi"] = round(float(values[-1]), 1)
        result["prev_cpi"] = round(float(values[-2]), 1)
        result["factor_value"] = result["current_cpi"]
        result["cpi_change"] = round(result["current_cpi"] - result["prev_cpi"], 1)

        if result["cpi_change"] > 0.3:
            result["cpi_trend"] = "加速上行"
        elif result["cpi_change"] > 0:
            result["cpi_trend"] = "缓慢上行"
        elif result["cpi_change"] < -0.3:
            result["cpi_trend"] = "加速下行"
        elif result["cpi_change"] < 0:
            result["cpi_trend"] = "缓慢下行"
        else:
            result["cpi_trend"] = "持平"

        current = result["current_cpi"]
        trend = result["cpi_trend"]
        if current < 0:
            result["inflation_regime"] = "通缩→需求不足→消费承压"
        elif current <= 2.0:
            result["inflation_regime"] = "温和通胀→需求健康→消费受益"
        elif current <= 3.0:
            result["inflation_regime"] = "正常偏高→中性"
        elif current <= 5.0:
            result["inflation_regime"] = "偏高→关注紧缩风险"
        else:
            result["inflation_regime"] = "恶性通胀→购买力侵蚀→消费承压"

        if trend and "加速" in trend and current > 3.0:
            result["inflation_regime"] += "+加速→警惕"

        # Add historical percentile as supplementary context
        if current is not None:
            cpi_col = None
            for c in ["全国-当月", "全国-同比增长", "value"]:
                if c in df.columns:
                    cpi_col = c
                    break
            if cpi_col:
                hist = pd.to_numeric(df[cpi_col], errors="coerce").dropna()
                if len(hist) >= 10:
                    result["cpi_percentile"] = round(self._rolling_percentile(current, hist, window=len(hist)), 1)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        regime = data.get("inflation_regime", "")
        cpi = data.get("current_cpi")
        trend = data.get("cpi_trend")

        if "温和通胀" in str(regime):
            return self._make_signal(
                asset="消费ETF(159928)", direction="BUY",
                reason=f"CPI={cpi}%，{regime}→企业有定价权→消费板块盈利稳定",
                holding_days=30, stop_loss=-0.05, confidence=0.55,
                strength=0.55, trigger="cpi_moderate_inflation",
                cpi=cpi, inflation_regime=regime,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=cpi,
            )

        if "恶性通胀" in str(regime):
            return self._make_signal(
                asset="消费ETF(159928)", direction="SELL",
                reason=f"CPI={cpi}%，{regime}→高通胀侵蚀购买力+紧缩预期→可选消费承压",
                holding_days=30, stop_loss=-0.03, confidence=0.60,
                strength=-0.60, trigger="cpi_hyperinflation",
                cpi=cpi, inflation_regime=regime,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=cpi,
            )

        if "通缩" in str(regime):
            return self._make_signal(
                asset="消费ETF(159928)", direction="SELL",
                reason=f"CPI={cpi}%，{regime}→消费者推迟购买→企业收入下降→利润压缩",
                holding_days=30, stop_loss=-0.03, confidence=0.55,
                strength=-0.55, trigger="cpi_deflation",
                cpi=cpi, inflation_regime=regime,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=cpi,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        cpi = data.get("current_cpi")
        if cpi is None:
            return 0.0
        if cpi < 0:
            return -0.5
        if cpi <= 2.0:
            return 0.5
        if cpi <= 3.0:
            return 0.0
        if cpi <= 5.0:
            return -0.3
        return -0.7