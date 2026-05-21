"""
汇率因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：人民币贬值 → 外资流出 → A股承压                                          │
│   人民币单日贬值>0.5% → 外资流出压力 → SELL 沪深300                              │
│   [逻辑：人民币贬值降低外资持有A股的美元计价回报，触发外资减持]                       │
│                                                                     │
│ 链条2：人民币极端贬值位 → 政策干预预期                                           │
│   人民币汇率Z-score>2 → 处于极端贬值位 → 央行可能干预 → 短期反弹 → 但先SELL         │
│   [逻辑：极端贬值位通常伴随资本外流压力，央行可能通过逆周期因子等手段干预]              │
│                                                                     │
│ 注意：汇率对A股的影响是非对称的——贬值利空明显，升值利好较弱                          │
│   - 贬值→外资流出→A股跌（直接、快速）                                          │
│   - 升值→外资流入→A股涨（间接、缓慢，还需看基本面）                                │
│                                                                     │
│ 数据：USD/CNY汇率(ak.currency_boc_sina)                                   │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="forex", category="macro",
    description="人民币汇率异动 → 进出口相关板块信号",
    asset="沪深300ETF(510300)", data_deps=["usd_cny"]
)
class ForexFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {"usd_cny": None, "daily_change": None, "factor_value": None}

        df = self.load("usd_cny")
        if df is None:
            return result

        col = None
        for candidate in ['close', 'value', 'DEXCHUS', 'usd_cny', 'USD_CNY']:
            if candidate in df.columns:
                col = candidate
                break
        if col is None:
            numeric_cols = [c for c in df.columns if c != 'date']
            col = numeric_cols[0] if numeric_cols else None
        if col is None:
            return result

        current = None
        if len(df) >= 2:
            current = self._safe_float(df.tail(1), -1, col=col)
            previous = self._safe_float(df.tail(2), -2, col=col)
            result["usd_cny"] = current
            result["factor_value"] = current
            result["daily_change"] = self._pct_change(current, previous)

        if len(df) >= 20:
            series = df[col].astype(float).tail(20)
            result["ma5"] = round(float(series.tail(5).mean()), 4)
            result["ma20"] = round(float(series.mean()), 4)
            if current:
                result["zscore_20d"] = self._zscore(current, series)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        if change is None:
            return None

        if change >= 0.005:
            return self._make_signal(
                asset="沪深300ETF(510300)", direction="SELL",
                reason=f"人民币单日贬值{change*100:.2f}%，外资流出压力",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=-0.5, trigger="cny_depreciation", daily_change=change,
            )

        if zscore is not None and zscore > 2.0:
            return self._make_signal(
                asset="沪深300ETF(510300)", direction="SELL",
                reason=f"人民币汇率Z-score={zscore:.1f}，处于极端贬值位",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=-0.55, trigger="cny_extreme_depreciation", zscore=zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        if zscore is not None:
            return max(-1.0, min(1.0, -zscore / 3.0))
        if change is not None:
            return max(-1.0, min(1.0, -change * 100))
        return 0.0