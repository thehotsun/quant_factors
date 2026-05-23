"""
VIX恐慌指数因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：VIX → 市场恐慌 → 风险资产承压 + 避险资产受益                            │
│   VIX↑ > 30 → 市场恐慌 → 风险资产(股票/商品)↓ + 避险资产(黄金/国债)↑              │
│   VIX↓ < 15 → 市场平静 → 风险偏好回升 → 风险资产↑                              │
│                                                                     │
│ 链条2：VIX极端值 → 均值回归                                                │
│   VIX > 35 → 极度恐慌 → 短期超卖 → 恐慌消退后反弹 → BUY 风险资产                  │
│   VIX < 12 → 过度乐观 → 警惕黑天鹅 → 适度减仓风险资产                            │
│                                                                     │
│ 链条3：VIX + 油价暴跌 → 流动性危机过滤器                                      │
│   油价暴跌 + VIX飙升 → 流动性危机（2020.3模式）→ 黄金也可能跌 → 现金为王            │
│   油价暴跌 + VIX平稳 → 正常供需调整 → 黄金避险逻辑成立                            │
│                                                                     │
│ 数据：AKShare index_vix (CBOE VIX)                                      │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="vix", category="macro",
    description="VIX恐慌指数：市场风险偏好→风险资产/避险资产轮动",
    asset="黄金期货(AU)", data_deps=["vix", "crude_oil_futures"]
)
class VixFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "vix_current": None,
            "vix_change": None,
            "vix_zscore": None,
            "risk_regime": None,
            "liquidity_crisis": None,
        }

        df = self.load("vix")
        if df is None or len(df) < 2:
            return result

        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        previous = self._safe_float(last_two, -2)
        result["vix_current"] = current
        result["vix_change"] = self._pct_change(current, previous)

        if len(df) >= 60:
            col = 'close' if 'close' in df.columns else df.columns[-1]
            close_series = df[col].astype(float)
            result["vix_zscore"] = self._zscore(current, close_series.tail(60)) if current else None
            result["vix_percentile"] = round(self._percentile(current, close_series.tail(60)) * 100, 1) if current else None

        if current is not None:
            if current > 35:
                result["risk_regime"] = "极度恐慌→风险资产超卖→恐慌消退后反弹"
            elif current > 30:
                result["risk_regime"] = "高度恐慌→避险情绪浓厚→利好黄金/国债"
            elif current > 25:
                result["risk_regime"] = "中度恐慌→风险偏好下降→偏空风险资产"
            elif current > 20:
                result["risk_regime"] = "轻度不安→正常偏高→中性偏谨慎"
            elif current > 15:
                result["risk_regime"] = "正常→市场平静→风险偏好正常"
            elif current > 12:
                result["risk_regime"] = "低波动→市场乐观→利好风险资产"
            else:
                result["risk_regime"] = "过度乐观→警惕黑天鹅→适度防御"

        oil_df = self.load("crude_oil_futures")
        if oil_df is not None and len(oil_df) >= 5:
            oil_current = self._safe_float(oil_df.tail(1), -1)
            oil_5d_ago = float(oil_df['close'].iloc[-5]) if 'close' in oil_df.columns else None
            oil_change = self._pct_change(oil_current, oil_5d_ago)
            if oil_change is not None and oil_change < -0.10 and current is not None and current > 30:
                result["liquidity_crisis"] = "油价暴跌+VIX飙升→流动性危机→现金为王→黄金也可能承压"

        result["factor_value"] = result.get("vix_current")
        result["factor_value_type"] = "raw_value" if result["factor_value"] is not None else None
        result["factor_direction"] = "lower_better"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        vix = data.get("vix_current")
        regime = data.get("risk_regime", "")
        crisis = data.get("liquidity_crisis")
        pct = data.get("vix_percentile")

        if crisis:
            return self._make_signal(
                asset="黄金期货(AU)", direction="SELL",
                reason=f"VIX={vix}+油价暴跌→流动性危机→现金为王→黄金短期承压",
                holding_days=5, stop_loss=-0.03, confidence=0.70,
                strength=-0.70, trigger="liquidity_crisis",
                vix=vix, risk_regime=regime, liquidity_crisis=crisis,
            )

        # Percentile-based thresholds (fallback to fixed if percentile unavailable)
        high_threshold = pct is not None and pct >= 90
        extreme_threshold = pct is not None and pct >= 95
        low_threshold = pct is not None and pct <= 10
        # Fallback to fixed thresholds
        if pct is None:
            high_threshold = vix is not None and vix > 30
            extreme_threshold = vix is not None and vix > 35
            low_threshold = vix is not None and vix < 12

        if high_threshold and not crisis:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"VIX={vix:.0f}(历史{pct:.0f}%分位)→市场恐慌→避险需求→利好黄金" if pct else f"VIX={vix:.0f}>30→市场恐慌→避险需求→利好黄金",
                holding_days=10, stop_loss=-0.03, confidence=0.65,
                strength=0.65, trigger="vix_high_gold_buy",
                vix=vix, risk_regime=regime, vix_percentile=pct,
            )

        if extreme_threshold:
            return self._make_signal(
                asset="沪深300(IF)", direction="BUY",
                reason=f"VIX={vix:.0f}(历史{pct:.0f}%分位)→极度恐慌→超卖→恐慌消退后反弹" if pct else f"VIX={vix:.0f}>35→极度恐慌→超卖→恐慌消退后反弹",
                holding_days=15, stop_loss=-0.05, confidence=0.60,
                strength=0.60, trigger="vix_extreme_equity_buy",
                vix=vix, risk_regime=regime, vix_percentile=pct,
            )

        if low_threshold:
            return self._make_signal(
                asset="沪深300(IF)", direction="SELL",
                reason=f"VIX={vix:.0f}(历史{pct:.0f}%分位)→过度乐观→警惕黑天鹅→适度减仓" if pct else f"VIX={vix:.0f}<12→过度乐观→警惕黑天鹅→适度减仓",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=-0.45, trigger="vix_complacency",
                vix=vix, risk_regime=regime, vix_percentile=pct,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        vix = data.get("vix_current")
        if vix is None:
            return 0.0
        if vix > 35:
            return 0.7
        if vix > 30:
            return 0.5
        if vix < 12:
            return -0.4
        return 0.0