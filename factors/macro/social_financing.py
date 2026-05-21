"""
社融因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：社融增速 → 实体经济资金需求 → A股领先指标                              │
│   社融存量增速↑ → 实体经济融资需求旺盛 → 经济复苏 → A股↑ → BUY 沪深300          │
│   社融存量增速↓ → 实体经济融资需求萎缩 → 经济下行 → A股↓ → SELL 沪深300          │
│                                                                     │
│ 链条2：M2-社融剪刀差 → 资金淤积/脱虚入实                                      │
│   M2增速 > 社融增速 → 资金淤积金融体系 → 利好债市/高股息 → 中性偏空A股            │
│   M2增速 < 社融增速 → 资金脱虚入实 → 实体经济活跃 → 利好A股 → BUY 沪深300        │
│                                                                     │
│ 链条3：社融结构 → 中长期贷款占比 → 投资信心                                    │
│   中长期贷款占比↑ → 企业投资信心强 → 经济内生动力足 → BUY 顺周期                 │
│   票据冲量占比↑ → 银行被动放贷 → 实体需求弱 → SELL 顺周期                       │
│                                                                     │
│ 数据：AKShare macro_china_shrzgm (社融规模增量月度)                           │
│       + macro_china_money_supply (M2)                                    │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof, latest_period_date, latest_release_date


@FactorRegistry.register(
    name="social_financing", category="macro",
    description="社融增速+M2-社融剪刀差：A股流动性领先指标",
    asset="沪深300(IF)", data_deps=["social_financing", "m2"]
)
class SocialFinancingFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "sf_growth": None,
            "m2_growth": None,
            "m2_sf_spread": None,
            "sf_trend": None,
            "signal": None,
            "factor_value": None,
            "period_date": None,
            "release_date": None,
        }

        sf_df = available_asof(self.load("social_financing"), "social_financing", self.params.get("as_of"))
        m2_df = available_asof(self.load("m2"), "m2", self.params.get("as_of"))

        if sf_df is not None and len(sf_df) >= 3:
            result["period_date"] = latest_period_date(sf_df)
            result["release_date"] = latest_release_date(sf_df)
            sf_df = sf_df.sort_values("月份") if "月份" in sf_df.columns else sf_df
            col = self._find_value_column(sf_df, ["社融规模增量", "社会融资规模增量", "value"])
            if col:
                recent = sf_df[col].tail(3).astype(float)
                result["sf_latest"] = float(recent.iloc[-1])
                result["sf_ma3"] = float(recent.mean())
                if "月份" in sf_df.columns:
                    sf_df["月份_dt"] = pd.to_datetime(sf_df["月份"].astype(str).str.replace("年", "-").str.replace("月", ""), errors="coerce")
                    latest_date = sf_df["月份_dt"].max()
                    if pd.notna(latest_date):
                        prev_year_date = latest_date - pd.DateOffset(years=1)
                        prev_year_rows = sf_df[sf_df["月份_dt"] <= prev_year_date].tail(3)
                        if len(prev_year_rows) >= 1:
                            prev_avg = float(prev_year_rows[col].astype(float).mean())
                            if prev_avg > 0:
                                result["sf_growth"] = round((result["sf_ma3"] / prev_avg - 1) * 100, 1)
                elif len(sf_df) >= 13:
                    prev_year = sf_df[col].iloc[-13:-10].astype(float)
                    prev_avg = float(prev_year.mean())
                    if prev_avg > 0:
                        result["sf_growth"] = round((result["sf_ma3"] / prev_avg - 1) * 100, 1)

                if len(sf_df) >= 6:
                    recent_6 = sf_df[col].tail(6).astype(float)
                    first_3 = float(recent_6.head(3).mean())
                    last_3 = float(recent_6.tail(3).mean())
                    if first_3 > 0:
                        result["sf_momentum"] = round((last_3 / first_3 - 1) * 100, 1)

        if m2_df is not None and len(m2_df) >= 3:
            col = self._find_value_column(m2_df, ["货币和准货币(M2)-同比增长", "M2", "m2", "货币和准货币(M2)", "value"])
            if col:
                recent = m2_df[col].tail(3).astype(float)
                result["m2_latest"] = float(recent.iloc[-1])
                result["m2_growth"] = result["m2_latest"]

        sf_g = result.get("sf_growth")
        m2_g = result.get("m2_growth")
        if sf_g is not None and m2_g is not None:
            result["m2_sf_spread"] = round(m2_g - sf_g, 1)
            result["factor_value"] = sf_g

        sf_mom = result.get("sf_momentum")
        if sf_g is not None:
            if sf_g > 12 and (sf_mom is not None and sf_mom > 0):
                result["sf_trend"] = "社融高速扩张→经济强复苏→利好A股"
                result["signal"] = "strong_buy"
            elif sf_g > 10:
                result["sf_trend"] = "社融稳健增长→经济温和复苏→偏多A股"
                result["signal"] = "buy"
            elif sf_g < 8 and (sf_mom is not None and sf_mom < 0):
                result["sf_trend"] = "社融收缩→经济下行压力→利空A股"
                result["signal"] = "sell"
            elif sf_g < 8:
                result["sf_trend"] = "社融偏弱→经济动能不足→偏空A股"
                result["signal"] = "weak_sell"
            else:
                result["sf_trend"] = "社融平稳→经济正常→中性"
                result["signal"] = "neutral"

        spread = result.get("m2_sf_spread")
        if spread is not None:
            if spread > 3:
                result["spread_signal"] = "资金淤积金融体系→利好债市/高股息"
            elif spread < -1:
                result["spread_signal"] = "资金脱虚入实→利好A股顺周期"
            else:
                result["spread_signal"] = "资金供需平衡→中性"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        sig = data.get("signal")
        spread = data.get("m2_sf_spread")

        if sig == "strong_buy" and spread is not None and spread < 1:
            return self._make_signal(
                asset="沪深300(IF)", direction="BUY",
                reason=f"社融增速{data['sf_growth']}%+M2-社融剪刀差{spread}%（资金脱虚入实）→强利好A股",
                holding_days=30, stop_loss=-0.05, confidence=0.75,
                strength=0.80, trigger="sf_strong_expansion",
                sf_growth=data["sf_growth"], m2_sf_spread=spread,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=data.get("sf_growth"),
            )

        if sig == "buy":
            return self._make_signal(
                asset="沪深300(IF)", direction="BUY",
                reason=f"社融增速{data['sf_growth']}%→经济温和复苏→利好A股",
                holding_days=20, stop_loss=-0.04, confidence=0.60,
                strength=0.55, trigger="sf_moderate_growth",
                sf_growth=data["sf_growth"],
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=data.get("sf_growth"),
            )

        if sig == "sell" and spread is not None and spread > 2:
            return self._make_signal(
                asset="沪深300(IF)", direction="SELL",
                reason=f"社融增速{data['sf_growth']}%+剪刀差{spread}%（资金淤积）→利空A股",
                holding_days=20, stop_loss=-0.04, confidence=0.70,
                strength=-0.70, trigger="sf_contraction",
                sf_growth=data["sf_growth"], m2_sf_spread=spread,
                period_date=data.get("period_date"), release_date=data.get("release_date"),
                factor_value=data.get("sf_growth"),
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        sig = data.get("signal")
        spread = data.get("m2_sf_spread")
        if sig == "strong_buy" and spread is not None and spread < 1:
            return 0.80
        if sig == "buy":
            return 0.50
        if sig == "sell":
            return -0.60
        if sig == "weak_sell":
            return -0.30
        return 0.0

    @staticmethod
    def _find_value_column(df: pd.DataFrame, candidates: list) -> str:
        for c in candidates:
            if c in df.columns:
                return c
        for c in df.columns:
            if "社融" in c or "增量" in c or "M2" in c or "m2" in c:
                return c
        return None