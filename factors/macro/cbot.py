"""
CBOT大豆因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：CBOT大豆 → 全球大豆定价锚 → 进口成本                                     │
│   CBOT大豆↑ → 进口大豆成本↑ → 豆粕↑ → 饲料↑                                   │
│   CBOT大豆↓ → 进口大豆成本↓ → 豆粕↓ → 饲料↓                                   │
│                                                                     │
│ 链条2：CBOT大豆 × 汇率 → 进口成本指数                                        │
│   CBOT大豆↑ + 人民币贬值 → 进口成本双重推升 → 国内大豆/豆粕↑                     │
│                                                                     │
│ 数据：CBOT大豆期货(ak.futures_foreign_hist) + USD/CNY汇率                    │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="cbot_soybean", category="macro",
    description="CBOT大豆：全球大豆定价锚→进口成本→豆粕/饲料传导",
    asset="豆粕期货(M)", data_deps=["cbot_soybean", "usd_cny"]
)
class CbotSoybeanFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "cbot_soybean": None,
            "daily_change": None,
        }

        df = self.load("cbot_soybean")
        if df is None or len(df) < 2:
            return result

        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        previous = self._safe_float(last_two, -2)
        result["cbot_soybean"] = current
        result["daily_change"] = self._pct_change(current, previous)

        if len(df) >= 20:
            close_series = df['close'].astype(float)
            result["ma20"] = float(close_series.tail(20).mean())
            if current:
                result["zscore_20d"] = self._zscore(current, close_series.tail(20))

        forex_df = self.load("usd_cny")
        if forex_df is not None and current:
            col = 'close' if 'close' in forex_df.columns else ('DEXCHUS' if 'DEXCHUS' in forex_df.columns else 'value')
            fx = self._safe_float(forex_df.tail(1), -1, col=col)
            if fx:
                result["import_cost_cny"] = round(current * fx, 2)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")

        if change is not None and change >= 0.03:
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"CBOT大豆单日上涨{change*100:.1f}%，进口成本推升→豆粕跟涨",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="cbot_soybean_surge",
                cbot_soybean=data.get("cbot_soybean"), daily_change=change,
            )

        if change is not None and change <= -0.03:
            return self._make_signal(
                asset="豆粕期货(M)", direction="SELL",
                reason=f"CBOT大豆单日下跌{abs(change)*100:.1f}%，进口成本下降→豆粕承压",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=-0.55, trigger="cbot_soybean_plunge",
                cbot_soybean=data.get("cbot_soybean"), daily_change=change,
            )

        if zscore is not None and zscore > 2.0:
            return self._make_signal(
                asset="豆粕期货(M)", direction="BUY",
                reason=f"CBOT大豆处于{zscore:.1f}σ高位，全球大豆偏紧",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="cbot_soybean_high_zscore",
                cbot_soybean=data.get("cbot_soybean"), zscore=zscore,
            )

        if zscore is not None and zscore < -2.0:
            return self._make_signal(
                asset="豆粕期货(M)", direction="SELL",
                reason=f"CBOT大豆处于{zscore:.1f}σ低位，全球大豆供应宽松",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=-0.60, trigger="cbot_soybean_low_zscore",
                cbot_soybean=data.get("cbot_soybean"), zscore=zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        change = data.get("daily_change")
        if zscore is not None:
            return max(-1.0, min(1.0, zscore / 3.0))
        if change is not None:
            return max(-1.0, min(1.0, change * 15))
        return 0.0