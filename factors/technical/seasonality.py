"""
季节性因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条：历史同期统计 → 当月季节性方向 → 交易信号                                      │
│                                                                     │
│   当月历史均收益>1% + 胜率>60% → 季节性强势 → BUY                                │
│     [逻辑：该月份历史上多次出现正收益，且胜率高，季节性规律可靠]                       │
│                                                                     │
│   当月历史均收益<-1% + 胜率<40% → 季节性弱势 → SELL                               │
│     [逻辑：该月份历史上多次出现负收益，季节性偏空]                                   │
│                                                                     │
│   当月历史均收益在-1%~1%之间 → 季节性中性 → 无信号                                 │
│                                                                     │
│ 典型季节性案例：                                                            │
│   - 螺纹钢：3-5月春季开工旺季、9-11月秋季赶工旺季 → 偏多                           │
│   - 天然气：12-2月冬季取暖旺季 → 偏多；3-5月淡季 → 偏空                            │
│   - 鸡蛋：8-9月中秋备货+夏季产蛋率低 → 偏多                                      │
│   - 黄金：12-1月春节+印度婚庆季 → 偏多                                           │
│                                                                     │
│ 适用品种：任意有5年以上历史数据的期货品种（通过symbol参数指定）                         │
│ 注意：季节性因子是统计规律，不是因果规律，需结合当年实际情况判断                          │
│   - 至少需要5年历史数据才有统计意义                                               │
│   - 季节性可能因政策、天气等异常因素失效                                           │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="seasonality", category="technical",
    description="季节性因子：历史同期涨跌统计 → 季节性方向判断",
    asset="通用(任意期货)", data_deps=[]
)
class SeasonalityFactor(BaseFactor):
    MIN_YEARS = 5  # 提高到5年，增加统计可靠性

    def __init__(self, data_dir: str = "./data", adaptive: bool = True,
                 params: Dict[str, Any] = None, symbol: str = None, data_bus=None):
        super().__init__(data_dir, adaptive, params, data_bus=data_bus)
        self.symbol = symbol

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_month": None, "seasonal_avg_return": None,
            "seasonal_win_rate": None, "seasonal_direction": None,
        }

        if not self.symbol:
            return result

        df = self.load(self.symbol)
        if df is None or len(df) < 252:
            return result

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.month
        df['year'] = df['date'].dt.year
        df['return'] = df['close'].astype(float).pct_change()

        current_month = df['month'].iloc[-1]
        result["current_month"] = int(current_month)

        monthly_returns = df.groupby(['year', 'month'])['return'].sum().reset_index()
        monthly_returns = monthly_returns.dropna()

        current_month_data = monthly_returns[monthly_returns['month'] == current_month]
        if len(current_month_data) >= self.MIN_YEARS:
            avg_return = float(current_month_data['return'].mean())
            win_count = int((current_month_data['return'] > 0).sum())
            total_count = len(current_month_data)
            win_rate = win_count / total_count

            result["seasonal_avg_return"] = round(avg_return, 4)
            result["seasonal_win_rate"] = round(win_rate, 2)
            result["seasonal_sample_years"] = total_count
            # Confidence decay for small samples
            if total_count < 10:
                result["seasonal_confidence_decay"] = round(total_count / 10.0, 2)
            else:
                result["seasonal_confidence_decay"] = 1.0

            if avg_return > 0.01 and win_rate > 0.6:
                result["seasonal_direction"] = "STRONG_BULLISH"
            elif avg_return > 0:
                result["seasonal_direction"] = "WEAK_BULLISH"
            elif avg_return < -0.01 and win_rate < 0.4:
                result["seasonal_direction"] = "STRONG_BEARISH"
            elif avg_return < 0:
                result["seasonal_direction"] = "WEAK_BEARISH"
            else:
                result["seasonal_direction"] = "NEUTRAL"

        result["factor_value"] = result.get("seasonal_avg_return")
        result["factor_value_type"] = "return" if result["factor_value"] is not None else None
        result["factor_direction"] = "two_sided"
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        direction = data.get("seasonal_direction")
        avg_return = data.get("seasonal_avg_return")
        win_rate = data.get("seasonal_win_rate")
        if direction is None:
            return None

        confidence_decay = data.get("seasonal_confidence_decay", 1.0)

        if direction == "STRONG_BULLISH":
            return self._make_signal(
                asset=self.symbol, direction="BUY",
                reason=f"{data['current_month']}月季节性强势(均收益{avg_return*100:.1f}%,胜率{win_rate*100:.0f}%,样本{data.get('seasonal_sample_years', '?')}年)",
                holding_days=20, stop_loss=-0.03, confidence=round(0.55 * confidence_decay, 2),
                strength=0.55, trigger="seasonal_strong_bullish",
                seasonal_avg_return=avg_return, seasonal_win_rate=win_rate,
                seasonal_sample_years=data.get("seasonal_sample_years"),
            )

        if direction == "STRONG_BEARISH":
            return self._make_signal(
                asset=self.symbol, direction="SELL",
                reason=f"{data['current_month']}月季节性弱势(均收益{avg_return*100:.1f}%,胜率{win_rate*100:.0f}%,样本{data.get('seasonal_sample_years', '?')}年)",
                holding_days=20, stop_loss=-0.03, confidence=round(0.55 * confidence_decay, 2),
                strength=-0.55, trigger="seasonal_strong_bearish",
                seasonal_avg_return=avg_return, seasonal_win_rate=win_rate,
                seasonal_sample_years=data.get("seasonal_sample_years"),
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        avg_return = data.get("seasonal_avg_return")
        win_rate = data.get("seasonal_win_rate")
        if avg_return is None or win_rate is None:
            return 0.0
        strength = np.tanh(avg_return * 50) * 0.5 + (win_rate - 0.5) * 1.0
        return max(-1.0, min(1.0, strength))