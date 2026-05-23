"""
汇率→商品传导因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：人民币贬值 → 进口商品成本上升 → 国内商品涨价                                   │
│   人民币5日贬值>1% + 大豆涨幅<汇率贬值幅度 → 进口成本传导滞后 → 大豆补涨 → BUY 豆粕   │
│     [逻辑：人民币贬值直接推升进口商品的人民币计价成本，但传导有1-2周滞后]               │
│                                                                     │
│ 链条2：人民币大幅贬值 → 进口商品全面承压/受益                                       │
│   人民币5日贬值>2% → 进口大豆/铜/原油成本全面上升 → BUY 豆粕（进口依赖度最高）         │
│     [逻辑：大幅贬值意味着进口成本系统性上升，进口依赖度高的品种受益最明显]               │
│                                                                     │
│ 链条3：人民币升值 → 进口成本下降 → 国内商品承压                                       │
│   人民币5日升值>1% → 进口成本下降 → SELL 豆粕                                       │
│                                                                     │
│ 进口依赖度参考：                                                              │
│   大豆 >80%（进口依赖度最高，汇率影响最大）                                         │
│   铜   >70%（进口精铜+铜精矿）                                                   │
│   原油 >70%（进口依赖度高）                                                       │
│                                                                     │
│ 数据：USD/CNY汇率 + 进口大豆期货(B) + 铜期货(CU) + 原油期货(SC)                      │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="forex_commodity", category="cross/system",
    description="人民币汇率→进口商品成本：贬值推升进口大豆/铜/原油成本",
    asset="豆粕期货(M)", data_deps=["usd_cny", "soybean_import_futures", "copper_futures", "crude_oil_futures"]
)
class ForexCommodityLink(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "usd_cny": None, "forex_change_5d": None, "forex_change_20d": None,
            "soybean_price": None, "soybean_change_5d": None,
            "copper_price": None, "copper_change_5d": None,
            "oil_price": None, "oil_change_5d": None,
        }

        forex_df = self.load("usd_cny")
        soybean_df = self.load("soybean_import_futures")
        copper_df = self.load("copper_futures")
        oil_df = self.load("crude_oil_futures")

        if forex_df is None:
            return result

        col = 'close' if 'close' in forex_df.columns else ('DEXCHUS' if 'DEXCHUS' in forex_df.columns else 'value')
        usd_cny = self._safe_float(forex_df.tail(1), -1, col=col)
        result["usd_cny"] = usd_cny

        if len(forex_df) >= 5:
            forex_5d = self._safe_float(forex_df.tail(5), -5, col=col)
            result["forex_change_5d"] = self._pct_change(usd_cny, forex_5d)
        if len(forex_df) >= 20:
            forex_20d = self._safe_float(forex_df.tail(20), -20, col=col)
            result["forex_change_20d"] = self._pct_change(usd_cny, forex_20d)

        if soybean_df is not None:
            sp = self._safe_float(soybean_df.tail(1), -1)
            result["soybean_price"] = sp
            if len(soybean_df) >= 5:
                sp5 = self._safe_float(soybean_df.tail(5), -5)
                result["soybean_change_5d"] = self._pct_change(sp, sp5)

        if copper_df is not None:
            cp = self._safe_float(copper_df.tail(1), -1)
            result["copper_price"] = cp
            if len(copper_df) >= 5:
                cp5 = self._safe_float(copper_df.tail(5), -5)
                result["copper_change_5d"] = self._pct_change(cp, cp5)

        if oil_df is not None:
            op = self._safe_float(oil_df.tail(1), -1)
            result["oil_price"] = op
            if len(oil_df) >= 5:
                op5 = self._safe_float(oil_df.tail(5), -5)
                result["oil_change_5d"] = self._pct_change(op, op5)

        result["factor_value"] = result.get("usd_cny")
        result["factor_value_type"] = "raw_value" if result["factor_value"] is not None else None
        result["factor_direction"] = "lower_better"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        forex_change = data.get("forex_change_5d")
        soybean_change = data.get("soybean_change_5d")

        if forex_change is None:
            return None

        regime = self._load_regime_data()

        if forex_change >= 0.01 and soybean_change is not None and soybean_change < forex_change:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "fx_cost")
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"人民币5日贬值{forex_change*100:.1f}%但大豆仅涨{soybean_change*100:.1f}%，进口成本传导滞后→大豆补涨",
                holding_days=10, stop_loss=-0.02, confidence=round(0.55 * regime_mult, 2),
                strength=0.55, trigger="forex_soybean_divergence",
                forex_change_5d=forex_change, soybean_change_5d=soybean_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )

        if forex_change >= 0.02:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "fx_cost")
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"人民币5日大幅贬值{forex_change*100:.1f}%，进口大豆成本上升→豆粕受益",
                holding_days=10, stop_loss=-0.02, confidence=round(0.55 * regime_mult, 2),
                strength=0.55, trigger="forex_depreciation_import",
                forex_change_5d=forex_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )

        if forex_change <= -0.01:
            regime_mult, regime_expl = self._regime_confidence_modifier(regime, "fx_cost")
            return self._make_signal(
                asset="豆粕期货(M)", direction="SELL",
                reason=f"人民币5日升值{abs(forex_change)*100:.1f}%，进口成本下降→豆粕承压",
                holding_days=5, stop_loss=-0.02, confidence=round(0.50 * regime_mult, 2),
                strength=-0.50, trigger="forex_appreciation_import",
                forex_change_5d=forex_change,
                risk_modifier=regime_mult, regime_note=regime_expl,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        forex_change = data.get("forex_change_5d")
        if forex_change is None:
            return 0.0
        return max(-1.0, min(1.0, forex_change * 50))