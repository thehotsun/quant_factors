"""
白银因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 链条1：金银比 → 白银相对估值 → 均值回归                                          │
│   金银比处于历史>90%分位 → 白银相对黄金极度低估 → BUY 白银                           │
│     [逻辑：金银比极端高意味着白银被严重低估，历史均值回归力量强]                        │
│     [历史：金银比长期均值约60-70，2020年3月曾飙升至120+，随后白银暴涨]                 │
│                                                                     │
│ 链条2：黄金上涨 → 白银补涨（贵金属属性）                                           │
│   黄金20日涨>3% + 白银涨幅<黄金 → 贵金属行情中白银滞涨 → 补涨预期 → BUY 白银          │
│     [逻辑：白银与黄金高度相关（相关系数~0.8），黄金大涨后白银通常会补涨]                 │
│                                                                     │
│ 链条3：PMI扩张 → 工业需求 → 白银工业属性受益                                        │
│   PMI>50 + PMI上升 + 白银Z-score<0 → 工业需求改善 → BUY 白银                        │
│     [逻辑：白银50%需求来自工业（电子、光伏、医疗），PMI扩张直接拉动工业用银需求]         │
│                                                                     │
│ 链条4：金银比极端低 → 白银相对黄金过度上涨 → SELL                                     │
│   金银比Z-score<-2 → 白银过度上涨 → 回调风险 → SELL 白银                             │
│                                                                     │
│ 白银的双重属性：                                                               │
│   贵金属属性（~50%）：跟随黄金，避险+抗通胀                                          │
│   工业属性（~50%）：电子+光伏+医疗，受PMI/工业周期驱动                                │
│   光伏用银：全球光伏银浆需求约3000吨/年，占白银总需求10%+，是增长最快的需求领域           │
│                                                                     │
│ 数据：白银期货(AG) + 黄金期货(AU) + PMI                                          │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry
from core.macro_calendar import available_asof


@FactorRegistry.register(
    name="silver", category="metals",
    description="白银：工业+贵金属双属性，监测金银比 + 光伏需求 + 工业PMI",
    asset="白银期货(AG)", data_deps=["silver_futures", "gold_futures", "pmi"]
)
class SilverFactor(BaseFactor):

    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "gold_price": None, "gold_silver_ratio": None,
            "ratio_percentile": None, "ratio_zscore": None,
            "pmi": None, "pmi_change": None,
            "zscore_20d": None, "percentile_20d": None,
            "gold_change_20d": None,
        }

        silver_df = self.load("silver_futures")
        if silver_df is None or len(silver_df) < 2:
            return result

        features = self._multi_window_features(silver_df)
        last_two = silver_df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(silver_df) >= 20:
            close = silver_df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None

        gold_df = self.load("gold_futures")
        if gold_df is not None and len(gold_df) >= 2:
            gold_current = self._safe_float(gold_df.tail(1), -1)
            result["gold_price"] = gold_current

            if gold_current and current and gold_current > 0:
                result["gold_silver_ratio"] = round(gold_current / current, 1)

            if len(gold_df) >= 20:
                gold_20d_ago = self._safe_float(gold_df.tail(20), -20)
                result["gold_change_20d"] = self._pct_change(gold_current, gold_20d_ago)

            min_len = min(len(silver_df), len(gold_df))
            if min_len >= 60:
                merged = pd.merge(
                    silver_df[['date', 'close']].rename(columns={'close': 'silver'}),
                    gold_df[['date', 'close']].rename(columns={'close': 'gold'}),
                    on='date', how='inner'
                )
                if len(merged) >= 20:
                    merged['ratio'] = merged['gold'] / merged['silver']
                    ratio_series = merged['ratio'].tail(60)
                    result["ratio_percentile"] = round(
                        self._percentile(result["gold_silver_ratio"], ratio_series) * 100, 1
                    )
                    result["ratio_zscore"] = round(
                        self._zscore(result["gold_silver_ratio"], ratio_series), 2
                    )

        pmi_df = available_asof(self.load("pmi"), "pmi")
        if pmi_df is not None and len(pmi_df) >= 2:
            col = 'value' if 'value' in pmi_df.columns else 'pmi'
            if col in pmi_df.columns:
                result["pmi"] = self._safe_float(pmi_df.tail(1), -1, col=col)
                prev_pmi = self._safe_float(pmi_df.tail(2), -2, col=col)
                result["pmi_change"] = round(result["pmi"] - prev_pmi, 2) if result["pmi"] and prev_pmi else None

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("gold_silver_ratio")
        ratio_percentile = data.get("ratio_percentile")
        ratio_zscore = data.get("ratio_zscore")
        gold_change = data.get("gold_change_20d")
        zscore = data.get("zscore_20d")
        pmi = data.get("pmi")
        pmi_change = data.get("pmi_change")

        if ratio_percentile is not None and ratio_percentile >= 90:
            return self._make_signal(
                asset="白银期货(AG)", direction="BUY",
                reason=f"金银比={ratio}处于历史{ratio_percentile:.0f}%分位，白银相对黄金极度低估→均值回归",
                holding_days=20, stop_loss=-0.03, confidence=0.65,
                strength=0.70, trigger="gold_silver_ratio_extreme",
                gold_silver_ratio=ratio, ratio_percentile=ratio_percentile,
            )

        if gold_change is not None and gold_change > 0.03 and zscore is not None and zscore < 0.5:
            return self._make_signal(
                asset="白银期货(AG)", direction="BUY",
                reason=f"黄金20日涨{gold_change*100:.1f}%但白银Z-score仅{zscore:.1f}，贵金属行情中白银滞涨→补涨预期",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="silver_lagging_gold",
                gold_change_20d=gold_change, zscore=zscore,
            )

        if pmi is not None and pmi > 50 and pmi_change is not None and pmi_change > 0 and zscore is not None and zscore < 0:
            return self._make_signal(
                asset="白银期货(AG)", direction="BUY",
                reason=f"PMI={pmi}扩张(+{pmi_change})→工业需求改善→白银工业属性受益",
                holding_days=15, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="silver_industrial_demand",
                pmi=pmi, pmi_change=pmi_change, zscore=zscore,
            )

        if ratio_zscore is not None and ratio_zscore <= -2.0:
            return self._make_signal(
                asset="白银期货(AG)", direction="SELL",
                reason=f"金银比Z-score={ratio_zscore:.1f}，白银相对黄金过度上涨→回调风险",
                holding_days=10, stop_loss=-0.02, confidence=0.50,
                strength=-0.50, trigger="silver_overvalued_vs_gold",
                gold_silver_ratio=ratio, ratio_zscore=ratio_zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        ratio_percentile = data.get("ratio_percentile")
        zscore = data.get("zscore_20d")
        if ratio_percentile is None or zscore is None:
            return 0.0
        ratio_signal = (ratio_percentile - 50) / 50
        price_signal = zscore / 3.0
        return max(-1.0, min(1.0, (ratio_signal * 0.6 + price_signal * 0.4)))