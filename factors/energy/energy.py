"""
能源因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 原油（CrudeOil）                                                       │
│                                                                     │
│ 链条1：EIA库存变化 → 供需平衡 → 油价方向（最重要的短期驱动）                    │
│   EIA库存↓（超预期去库）→ 供给偏紧 → 油价↑ → BUY                            │
│   EIA库存↑（超预期累库）→ 供给过剩 → 油价↓ → SELL                            │
│   [数据：EIA每周三发布，AKShare: ak.energy_eia_crude]                      │
│                                                                     │
│ 链条2：价格极端值 → 均值回归                                              │
│   Z-score<-2 → 超卖 → BUY                                             │
│   Z-score>2 → 超买 → SELL                                             │
│                                                                     │
│ 链条3：价格突破 → 趋势跟踪                                              │
│   单日涨幅>自适应阈值 → 短期动能 → BUY                                     │
│                                                                     │
│ 链条4：期限结构（backwardation/contango）→ 现货供需                         │
│   近月>远月（backwardation）→ 现货紧缺 → BUY                               │
│   近月<远月（contango）→ 供应宽松 → SELL                                   │
│   [数据：需近远月合约价格，预留接口]                                         │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ 天然气（NaturalGas）                                                    │
│                                                                     │
│ 链条1：季节性（天然气最核心特征）                                           │
│   冬季(12-2月)：取暖需求↑ → 天然气↑ → BUY（但需看库存是否充足）                 │
│   夏季(6-8月)：发电制冷需求↑ → 天然气↑ → BUY                                │
│   春秋(3-5月,9-11月)：需求淡季 → 天然气↓ → SELL                             │
│                                                                     │
│ 链条2：EIA天然气库存                                                     │
│   库存低于5年均值 → 供给偏紧 → BUY                                        │
│   库存高于5年均值 → 供给过剩 → SELL                                        │
│   [数据：EIA每周四发布]                                                   │
│                                                                     │
│ 注意：国内无天然气期货直接交易标的，此因子主要用于能源板块联动分析                    │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ 油气比（OilGasRatio）                                                   │
│                                                                     │
│ 链条：原油/天然气比值 → 能源替代经济性 → 均值回归                              │
│   油气比>历史80分位 → 天然气相对原油极度低估 → BUY天然气                       │
│   油气比<历史20分位 → 天然气相对原油高估 → SELL天然气                          │
│   [逻辑：油气在工业/发电领域可互相替代，极端比值会回归]                           │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
import pandas as pd
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="crude_oil", category="energy",
    description="原油：EIA库存变化+价格极端值+趋势突破→油价方向判断",
    asset="原油期货(SC)", data_deps=["crude_oil_futures", "eia_crude_stock"]
)
class CrudeOilFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "zscore_20d": None, "percentile_20d": None,
            "eia_stock_change": None, "eia_stock_direction": None,
            "adaptive_threshold": None,
        }

        df = self.load("crude_oil_futures")
        if df is None or len(df) < 2:
            return result

        features = self._multi_window_features(df)
        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(df) >= 20:
            close_series = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close_series.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close_series.tail(20)) if current else None
            result["adaptive_threshold"] = self._adaptive_threshold("oil_change", 0.03, close_series)

        eia_df = self.load("eia_crude_stock")
        if eia_df is not None and len(eia_df) >= 2:
            col = 'value' if 'value' in eia_df.columns else 'stock'
            if col in eia_df.columns:
                latest = self._safe_float(eia_df.tail(1), -1, col=col)
                prev = self._safe_float(eia_df.tail(2), -2, col=col)
                if latest and prev:
                    result["eia_stock_change"] = round(latest - prev, 1)
                    if result["eia_stock_change"] < -100:
                        result["eia_stock_direction"] = "大幅去库→供给偏紧→利多油价"
                    elif result["eia_stock_change"] < 0:
                        result["eia_stock_direction"] = "小幅去库→中性偏多"
                    elif result["eia_stock_change"] > 100:
                        result["eia_stock_direction"] = "大幅累库→供给过剩→利空油价"
                    elif result["eia_stock_change"] > 0:
                        result["eia_stock_direction"] = "小幅累库→中性偏空"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        change = data.get("daily_change")
        zscore = data.get("zscore_20d")
        threshold = data.get("adaptive_threshold", 0.03)
        stock_dir = data.get("eia_stock_direction")

        if stock_dir and "大幅去库" in str(stock_dir) and zscore is not None and zscore < 1.5:
            return self._make_signal(
                asset="原油期货(SC)", direction="BUY",
                reason=f"EIA{stock_dir}，Z-score={zscore:.1f}→供需偏紧+价格未过热→做多",
                holding_days=10, stop_loss=-0.03, confidence=0.65,
                strength=0.65, trigger="oil_eia_draw",
                eia_stock_direction=stock_dir, zscore=zscore,
            )

        if stock_dir and "大幅累库" in str(stock_dir):
            return self._make_signal(
                asset="原油期货(SC)", direction="SELL",
                reason=f"EIA{stock_dir}→供给过剩→油价承压",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=-0.60, trigger="oil_eia_build",
                eia_stock_direction=stock_dir,
            )

        if zscore is not None and zscore <= -2.0:
            return self._make_signal(
                asset="原油期货(SC)", direction="BUY",
                reason=f"原油Z-score={zscore:.1f}，极端低位→超卖反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.60,
                strength=min(1.0, abs(zscore) / 3.0),
                trigger="oil_zscore_low", zscore=zscore,
            )

        if zscore is not None and zscore >= 2.0:
            return self._make_signal(
                asset="原油期货(SC)", direction="SELL",
                reason=f"原油Z-score={zscore:.1f}，极端高位→超买回调",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=-min(1.0, zscore / 3.0), trigger="oil_zscore_high", zscore=zscore,
            )

        if change is not None and threshold and change >= threshold:
            return self._make_signal(
                asset="原油期货(SC)", direction="BUY",
                reason=f"原油单日涨{change*100:.1f}%，突破自适应阈值{threshold*100:.1f}%→短期动能",
                holding_days=5, stop_loss=-0.02, confidence=0.55,
                strength=min(1.0, change / threshold * 0.8),
                trigger="oil_surge", daily_change=change,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        percentile = data.get("percentile_20d")
        change = data.get("daily_change")
        stock_dir = data.get("eia_stock_direction")
        strength = self._continuous_signal(zscore, percentile, change, change_is_cost=False)
        if stock_dir and "去库" in str(stock_dir):
            strength += 0.2
        elif stock_dir and "累库" in str(stock_dir):
            strength -= 0.2
        return max(-1.0, min(1.0, strength))


@FactorRegistry.register(
    name="natural_gas", category="energy",
    description="天然气：季节性+库存→能源板块联动（国内无直接标的，用于联动分析）",
    asset="天然气期货(NG)", data_deps=["natural_gas_futures"]
)
class NaturalGasFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "zscore_20d": None, "percentile_20d": None,
            "current_month": None, "seasonal_phase": None,
            "inventory_signal": None, "seasonal_strength": None,
        }

        df = self.load("natural_gas_futures")
        if df is None or len(df) < 2:
            return result

        features = self._multi_window_features(df)
        last_two = df.tail(2)
        current = self._safe_float(last_two, -1)
        yesterday = self._safe_float(last_two, -2)
        change = self._pct_change(current, yesterday)

        result["current_price"] = current
        result["daily_change"] = change
        result.update(features)

        if len(df) >= 20:
            close_series = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close_series.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close_series.tail(20)) if current else None

        if len(df) >= 1260:
            close_series = df['close'].astype(float)
            result["percentile_5y"] = self._percentile(current, close_series.tail(1260)) if current else None

        import datetime
        month = datetime.datetime.now().month
        result["current_month"] = month
        if month in [12, 1, 2]:
            result["seasonal_phase"] = "冬季取暖旺季→需求高峰→利多"
            result["seasonal_strength"] = 0.3
        elif month in [6, 7, 8]:
            result["seasonal_phase"] = "夏季发电旺季→需求次高峰→偏多"
            result["seasonal_strength"] = 0.15
        elif month in [3, 4, 5]:
            result["seasonal_phase"] = "春季淡季→库存回补→偏空"
            result["seasonal_strength"] = -0.2
        else:
            result["seasonal_phase"] = "秋季淡季→需求回落→偏空"
            result["seasonal_strength"] = -0.15

        pct_5y = result.get("percentile_5y")
        if pct_5y is not None:
            if pct_5y < 0.2:
                result["inventory_signal"] = "价格处于5年低位→隐含库存充裕→偏空"
            elif pct_5y < 0.4:
                result["inventory_signal"] = "价格偏低→隐含库存偏宽松→略偏空"
            elif pct_5y > 0.8:
                result["inventory_signal"] = "价格处于5年高位→隐含库存紧张→偏多"
            elif pct_5y > 0.6:
                result["inventory_signal"] = "价格偏高→隐含库存偏紧→略偏多"
            else:
                result["inventory_signal"] = "价格适中→隐含库存正常→中性"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        seasonal = data.get("seasonal_phase", "")
        pct_5y = data.get("percentile_5y")

        if zscore is not None and zscore <= -2.0 and "旺季" in str(seasonal):
            extra = ""
            confidence = 0.60
            if pct_5y is not None and pct_5y < 0.3:
                extra = "+5年价格低位→库存可能紧张→信号增强"
                confidence = 0.70
            return self._make_signal(
                asset="天然气期货(NG)", direction="BUY",
                reason=f"天然气Z-score={zscore:.1f}低位+{seasonal}{extra}→季节性需求+超卖→反弹",
                holding_days=10, stop_loss=-0.03, confidence=confidence,
                strength=confidence, trigger="gas_seasonal_low",
                zscore=zscore, seasonal_phase=seasonal, percentile_5y=pct_5y,
            )

        if zscore is not None and zscore >= 2.0 and "淡季" in str(seasonal):
            extra = ""
            confidence = 0.55
            if pct_5y is not None and pct_5y > 0.7:
                extra = "+5年价格高位→库存可能充裕→信号增强"
                confidence = 0.65
            return self._make_signal(
                asset="天然气期货(NG)", direction="SELL",
                reason=f"天然气Z-score={zscore:.1f}高位+{seasonal}{extra}→淡季需求弱+超买→回调",
                holding_days=10, stop_loss=-0.03, confidence=confidence,
                strength=-confidence, trigger="gas_seasonal_high",
                zscore=zscore, seasonal_phase=seasonal, percentile_5y=pct_5y,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        seasonal = data.get("seasonal_phase", "")
        pct_5y = data.get("percentile_5y")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if "旺季" in str(seasonal):
            strength += 0.15
        elif "淡季" in str(seasonal):
            strength -= 0.15
        if pct_5y is not None:
            if pct_5y < 0.2:
                strength += 0.1
            elif pct_5y > 0.8:
                strength -= 0.1
        return max(-1.0, min(1.0, strength))


@FactorRegistry.register(
    name="oil_gas_ratio", category="energy",
    description="油气比：原油/天然气比值→能源替代→均值回归（历史分位替代固定阈值）",
    asset="原油期货(SC)", data_deps=["crude_oil_futures", "natural_gas_futures"]
)
class OilGasRatio(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "oil_gas_ratio": None, "oil_price": None, "gas_price": None,
            "ratio_percentile": None, "ratio_zscore": None,
        }

        oil_df = self.load("crude_oil_futures")
        gas_df = self.load("natural_gas_futures")
        if oil_df is None or gas_df is None:
            return result

        oil_price = self._safe_float(oil_df.tail(1), -1)
        gas_price = self._safe_float(gas_df.tail(1), -1)
        if oil_price is None or gas_price is None or gas_price == 0:
            return result

        result["oil_price"] = oil_price
        result["gas_price"] = gas_price
        result["oil_gas_ratio"] = round(oil_price / gas_price, 2)

        min_len = min(len(oil_df), len(gas_df))
        if min_len >= 60:
            merged = pd.merge(
                oil_df[['date', 'close']].rename(columns={'close': 'oil'}),
                gas_df[['date', 'close']].rename(columns={'close': 'gas'}),
                on='date', how='inner'
            )
            if len(merged) >= 20:
                merged['ratio'] = merged['oil'] / merged['gas']
                ratio_series = merged['ratio'].tail(60)
                result["ratio_percentile"] = round(
                    self._percentile(result["oil_gas_ratio"], ratio_series) * 100, 1
                )
                result["ratio_zscore"] = round(
                    self._zscore(result["oil_gas_ratio"], ratio_series), 2
                )

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        ratio = data.get("oil_gas_ratio")
        percentile = data.get("ratio_percentile")
        if ratio is None:
            return None

        if percentile is not None and percentile >= 80:
            return self._make_signal(
                asset="天然气期货(NG)", direction="BUY",
                reason=f"油气比{ratio:.1f}处于历史{percentile:.0f}%分位→天然气相对原油极度低估→均值回归→BUY天然气",
                holding_days=15, stop_loss=-0.04, confidence=0.60,
                strength=0.60, trigger="oil_gas_ratio_extreme",
                oil_gas_ratio=ratio, ratio_percentile=percentile,
            )

        if percentile is not None and percentile <= 20:
            return self._make_signal(
                asset="天然气期货(NG)", direction="SELL",
                reason=f"油气比{ratio:.1f}处于历史{percentile:.0f}%分位→天然气相对原油高估→均值回归→SELL天然气",
                holding_days=15, stop_loss=-0.04, confidence=0.55,
                strength=-0.55, trigger="oil_gas_ratio_low",
                oil_gas_ratio=ratio, ratio_percentile=percentile,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        percentile = data.get("ratio_percentile")
        if percentile is None:
            return 0.0
        return (percentile / 100 - 0.5) * 2