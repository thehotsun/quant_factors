"""
金属因子 — 影响链条

┌─────────────────────────────────────────────────────────────────────┐
│ 铜（Copper）— 工业消耗品，"铜博士"                                          │
│                                                                     │
│ 链条1：PMI → 制造业需求 → 铜价（铜是工业金属之王，与PMI高度正相关）                │
│   PMI>50+PMI↑+铜价未涨 → 需求改善未定价 → BUY                              │
│   PMI<50+PMI↓ → 需求萎缩 → SELL                                         │
│                                                                     │
│ 链条2：库存 → 供需平衡（LME+上期所+保税区）                                    │
│   库存↓ → 供给偏紧 → BUY                                                 │
│   库存↑ → 需求疲软 → SELL                                                │
│   [数据：LME/上期所每周发布，AKShare暂不支持，预留接口]                          │
│                                                                     │
│ 链条3：期限结构 → 现货紧张程度                                             │
│   近月>远月（backwardation）→ 现货紧缺 → BUY                               │
│   近月<远月（contango）→ 供应宽松 → SELL                                   │
│                                                                     │
│ 链条4：TC/RC加工费 → 矿端供给                                             │
│   TC/RC↓ → 铜矿供给偏紧 → 冶炼减产 → 铜价↑ → BUY                            │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ 铝（Aluminum）— 能源密集型工业金属，"固态电力"                                 │
│                                                                     │
│ 链条1：动力煤价格 → 电力成本 → 电解铝利润 → 减产/复产                           │
│   动力煤↑ → 电力成本↑（占铝成本40%）→ 电解铝亏损 → 减产 → 供给收缩 → 铝价↑ → BUY  │
│   动力煤↓ → 电力成本↓ → 利润改善 → 复产 → 供给增加 → 铝价↓ → SELL               │
│   [数据：动力煤期货(ZC)，中国电解铝70%用煤电]                                  │
│                                                                     │
│ 链条2：铝价极端值 → 均值回归                                              │
│   Z-score<-2 → 超卖+成本支撑 → BUY                                       │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ 螺纹钢（Rebar）— 建筑/基建材料                                              │
│                                                                     │
│ 链条1：季节性 → 开工需求                                                 │
│   3-5月（春季开工）+9-11月（秋季赶工）→ 旺季需求↑ → BUY                        │
│   12-2月（冬季停工）+6-8月（高温雨季）→ 淡季需求↓ → SELL                        │
│                                                                     │
│ 链条2：库存周期（Mysteel每周厂库+社库）                                      │
│   去库速度>5% → 需求旺盛 → BUY                                            │
│   累库速度>5% → 需求疲软 → SELL                                           │
│   [数据：Mysteel每周四发布，AKShare暂不支持，预留接口]                          │
│                                                                     │
│ 链条3：房地产新开工面积（领先6-9个月）                                        │
│   新开工↑ → 6个月后螺纹钢需求↑ → BUY                                       │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ 黄金（Gold）— 避险资产/货币替代                                             │
│                                                                     │
│ 链条1：实际利率（TIPS收益率）→ 黄金机会成本（最重要的单一驱动因子）                  │
│   实际利率↓ → 持有黄金机会成本↓ → 黄金↑ → BUY                                │
│   实际利率↑ → 持有黄金机会成本↑ → 黄金↓ → SELL                                │
│   [数据：美国TIPS收益率，AKShare暂不支持，预留接口]                             │
│                                                                     │
│ 链条2：美元/人民币汇率 → 本币计价黄金                                         │
│   人民币贬值 → 本币计价黄金上涨（对冲汇率风险）→ BUY                              │
│                                                                     │
│ 链条3：原油价格 → 通胀预期 → 黄金抗通胀需求                                    │
│   原油↑ → 通胀预期↑ → 黄金抗通胀需求↑ → BUY                                  │
│                                                                     │
│ 链条4：波动率 → 市场恐慌                                                  │
│   黄金波动率↑+价格高位 → 短期过热 → SELL                                     │
│   黄金Z-score极端低 → 超卖 → BUY                                          │
└─────────────────────────────────────────────────────────────────────┘
"""
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="copper", category="metals",
    description="铜：工业消耗品，PMI方向+库存+期限结构→工业需求判断",
    asset="铜期货(CU)", data_deps=["copper_futures", "pmi"]
)
class CopperFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "pmi": None, "pmi_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
        }

        df = self.load("copper_futures")
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

        if len(df) >= 60:
            close = df['close'].astype(float)
            result["ma20"] = round(float(close.tail(20).mean()), 2)
            result["ma60"] = round(float(close.tail(60).mean()), 2)
            result["trend"] = "上涨" if result["ma20"] > result["ma60"] else "下跌"
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None

        pmi_df = self.load("pmi")
        if pmi_df is not None and len(pmi_df) >= 2:
            col = 'value' if 'value' in pmi_df.columns else 'pmi'
            if col in pmi_df.columns:
                result["pmi"] = self._safe_float(pmi_df.tail(1), -1, col=col)
                prev_pmi = self._safe_float(pmi_df.tail(2), -2, col=col)
                result["pmi_change"] = round(result["pmi"] - prev_pmi, 2) if result["pmi"] and prev_pmi else None

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        pmi = data.get("pmi")
        pmi_change = data.get("pmi_change")
        zscore = data.get("zscore_20d")
        trend = data.get("trend")

        if pmi is not None and pmi_change is not None and pmi > 50 and pmi_change > 0 and zscore is not None and zscore < 1.0:
            return self._make_signal(
                asset="铜期货(CU)", direction="BUY",
                reason=f"PMI={pmi}扩张(+{pmi_change})但铜Z-score仅{zscore:.1f}→制造业需求改善未充分定价→补涨预期",
                holding_days=15, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="pmi_copper_divergence",
                pmi=pmi, pmi_change=pmi_change, zscore=zscore,
            )

        if zscore is not None and zscore <= -2.0:
            return self._make_signal(
                asset="铜期货(CU)", direction="BUY",
                reason=f"铜Z-score={zscore:.1f}，极端低位→供给端可能减产+成本支撑→反弹预期",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="copper_extreme_low", zscore=zscore,
            )

        if trend == "下跌" and zscore is not None and zscore < -1.5:
            return self._make_signal(
                asset="铜期货(CU)", direction="BUY",
                reason=f"铜价跌破60日均线，Z-score={zscore:.1f}→趋势破位但接近超卖→关注反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.50,
                strength=0.50, trigger="copper_trend_break_oversold",
                trend=trend, zscore=zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        pmi = data.get("pmi")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if pmi is not None and pmi > 50:
            strength += 0.2
        return max(-1.0, min(1.0, strength))


@FactorRegistry.register(
    name="aluminum", category="metals",
    description="铝：能源密集型工业金属，动力煤→电力成本→减产/复产→铝价",
    asset="铝期货(AL)", data_deps=["aluminum_futures", "thermal_coal_futures"]
)
class AluminumFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "coal_price": None, "coal_change_20d": None,
            "energy_cost_pressure": None,
            "zscore_20d": None, "percentile_20d": None,
        }

        df = self.load("aluminum_futures")
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
            close = df['close'].astype(float)
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None

        from datetime import datetime
        month = datetime.now().month
        if month in [11, 12, 1, 2, 3, 4]:
            result["yunnan_hydro"] = "枯水期→水电发电不足→云南电解铝限产→供给收缩→利多铝价"
            result["yunnan_hydro_strength"] = 0.25
        elif month in [5, 6]:
            result["yunnan_hydro"] = "丰水期初期→水电恢复→复产预期→偏空铝价"
            result["yunnan_hydro_strength"] = -0.10
        elif month in [7, 8, 9, 10]:
            result["yunnan_hydro"] = "丰水期→水电充裕→满产→供给宽松→偏空铝价"
            result["yunnan_hydro_strength"] = -0.15
        else:
            result["yunnan_hydro"] = "过渡期"
            result["yunnan_hydro_strength"] = 0.0

        coal_df = self.load("thermal_coal_futures")
        if coal_df is not None and len(coal_df) >= 20:
            coal_current = self._safe_float(coal_df.tail(1), -1)
            coal_20d_ago = self._safe_float(coal_df.tail(20), -20)
            result["coal_price"] = coal_current
            result["coal_change_20d"] = self._pct_change(coal_current, coal_20d_ago)

            if result["coal_change_20d"] is not None:
                if result["coal_change_20d"] > 0.10:
                    result["energy_cost_pressure"] = "高（动力煤大涨→电力成本飙升→减产风险）"
                elif result["coal_change_20d"] > 0.05:
                    result["energy_cost_pressure"] = "中（动力煤上涨→电力成本上升）"
                elif result["coal_change_20d"] < -0.05:
                    result["energy_cost_pressure"] = "低（动力煤下跌→电力成本下降→利润改善）"
                else:
                    result["energy_cost_pressure"] = "正常"

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        yunnan = data.get("yunnan_hydro", "")
        # 注：动力煤触发条件已移除（ZC合约受政策限价冻结在801.4，不再产生有效信号）

        if zscore is not None and zscore <= -2.0:
            extra = ""
            confidence = 0.55
            if "枯水期" in str(yunnan):
                extra = "+云南枯水期限产"
                confidence = 0.65
            return self._make_signal(
                asset="铝期货(AL)", direction="BUY",
                reason=f"铝Z-score={zscore:.1f}极端低位{extra}→成本支撑+减产→反弹",
                holding_days=10, stop_loss=-0.03, confidence=confidence,
                strength=confidence, trigger="aluminum_extreme_low", zscore=zscore,
                yunnan_hydro=yunnan,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        hydro_strength = data.get("yunnan_hydro_strength", 0)
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        # 注：动力煤贡献已移除（ZC合约受政策限价冻结）
        strength += hydro_strength
        return max(-1.0, min(1.0, strength))


@FactorRegistry.register(
    name="rebar", category="metals",
    description="螺纹钢：建筑/基建材料，季节性+库存周期→开工需求判断",
    asset="螺纹钢期货(RB)", data_deps=["rebar_futures"]
)
class RebarFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "season": None, "is_peak_season": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "volatility_20d": None,
        }

        df = self.load("rebar_futures")
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

        from datetime import datetime
        month = datetime.now().month
        if month in [3, 4, 5]:
            result["season"] = "春季开工旺季→需求释放"
            result["is_peak_season"] = True
        elif month in [9, 10, 11]:
            result["season"] = "秋季赶工旺季→需求次高峰"
            result["is_peak_season"] = True
        elif month in [12, 1, 2]:
            result["season"] = "冬季停工淡季→需求冰点"
            result["is_peak_season"] = False
        else:
            result["season"] = "夏季高温雨季→施工放缓"
            result["is_peak_season"] = False

        if len(df) >= 60:
            close = df['close'].astype(float)
            result["ma20"] = round(float(close.tail(20).mean()), 2)
            result["ma60"] = round(float(close.tail(60).mean()), 2)
            result["trend"] = "上涨" if result["ma20"] > result["ma60"] else "下跌"
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None
            result["volatility_20d"] = round(float(close.pct_change().tail(20).std()), 4)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        is_peak = data.get("is_peak_season")
        zscore = data.get("zscore_20d")
        trend = data.get("trend")
        season = data.get("season")

        if is_peak and zscore is not None and zscore < 0 and trend == "下跌":
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"{season}，螺纹钢Z-score={zscore:.1f}趋势偏弱→旺季需求即将释放→提前布局",
                holding_days=20, stop_loss=-0.03, confidence=0.60,
                strength=0.60, trigger="rebar_peak_season_dip",
                season=season, zscore=zscore, trend=trend,
            )

        if not is_peak and zscore is not None and zscore > 1.5:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="SELL",
                reason=f"{season}，螺纹钢Z-score={zscore:.1f}偏高→淡季需求不足→回调风险",
                holding_days=10, stop_loss=-0.02, confidence=0.50,
                strength=-0.50, trigger="rebar_off_season_high",
                season=season, zscore=zscore,
            )

        if zscore is not None and zscore <= -2.0:
            return self._make_signal(
                asset="螺纹钢期货(RB)", direction="BUY",
                reason=f"螺纹钢Z-score={zscore:.1f}，极端低位→成本支撑+政策预期→反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="rebar_extreme_low", zscore=zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        is_peak = data.get("is_peak_season")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if is_peak:
            strength += 0.2
        return max(-1.0, min(1.0, strength))


@FactorRegistry.register(
    name="gold", category="metals",
    description="黄金：避险资产/货币替代，实际利率+美元+通胀预期+波动率→金价方向",
    asset="黄金期货(AU)", data_deps=["gold_futures", "usd_cny", "crude_oil_futures", "tips_yield"]
)
class GoldFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        result = {
            "current_price": None, "daily_change": None,
            "usd_cny": None, "forex_change_20d": None,
            "oil_change_20d": None, "tips_yield": None, "tips_change": None,
            "ma20": None, "ma60": None, "trend": None,
            "zscore_20d": None, "percentile_20d": None,
            "volatility_20d": None,
        }

        df = self.load("gold_futures")
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

        if len(df) >= 60:
            close = df['close'].astype(float)
            result["ma20"] = round(float(close.tail(20).mean()), 2)
            result["ma60"] = round(float(close.tail(60).mean()), 2)
            result["trend"] = "上涨" if result["ma20"] > result["ma60"] else "下跌"
            result["zscore_20d"] = self._zscore(current, close.tail(20)) if current else None
            result["percentile_20d"] = self._percentile(current, close.tail(20)) if current else None
            result["volatility_20d"] = round(float(close.pct_change().tail(20).std()), 4)

        forex_df = self.load("usd_cny")
        if forex_df is not None and len(forex_df) >= 20:
            col = 'close' if 'close' in forex_df.columns else 'value'
            if col in forex_df.columns:
                result["usd_cny"] = self._safe_float(forex_df.tail(1), -1, col=col)
                forex_20d = self._safe_float(forex_df.tail(20), -20, col=col)
                result["forex_change_20d"] = self._pct_change(result["usd_cny"], forex_20d)

        oil_df = self.load("crude_oil_futures")
        if oil_df is not None and len(oil_df) >= 20:
            oil_now = self._safe_float(oil_df.tail(1), -1)
            oil_20d = self._safe_float(oil_df.tail(20), -20)
            result["oil_change_20d"] = self._pct_change(oil_now, oil_20d)

        tips_df = self.load("tips_yield")
        if tips_df is not None and len(tips_df) >= 2:
            col = 'value' if 'value' in tips_df.columns else 'yield'
            if col in tips_df.columns:
                result["tips_yield"] = self._safe_float(tips_df.tail(1), -1, col=col)
                prev_tips = self._safe_float(tips_df.tail(2), -2, col=col)
                if result["tips_yield"] and prev_tips:
                    result["tips_change"] = round(result["tips_yield"] - prev_tips, 4)

        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        forex_change = data.get("forex_change_20d")
        oil_change = data.get("oil_change_20d")
        tips_change = data.get("tips_change")
        zscore = data.get("zscore_20d")
        vol = data.get("volatility_20d")

        if tips_change is not None and tips_change < -0.05 and zscore is not None and zscore < 1.5:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"TIPS收益率下降{tips_change*100:.1f}bp→实际利率下行→持有黄金机会成本下降→金价受益",
                holding_days=15, stop_loss=-0.03, confidence=0.65,
                strength=0.65, trigger="gold_real_rate_down",
                tips_change=tips_change, zscore=zscore,
            )

        if forex_change is not None and forex_change > 0.01 and zscore is not None and zscore < 1.0:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"人民币20日贬值{forex_change*100:.1f}%→本币贬值→黄金对冲需求→金价受益",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="gold_forex_hedge",
                forex_change_20d=forex_change, zscore=zscore,
            )

        if oil_change is not None and oil_change > 0.10 and zscore is not None and zscore < 1.5:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"原油20日涨{oil_change*100:.1f}%→通胀预期升温→黄金抗通胀需求",
                holding_days=10, stop_loss=-0.02, confidence=0.55,
                strength=0.55, trigger="gold_inflation_hedge",
                oil_change_20d=oil_change, zscore=zscore,
            )

        if vol is not None and vol > 0.02 and zscore is not None and zscore > 1.5:
            return self._make_signal(
                asset="黄金期货(AU)", direction="SELL",
                reason=f"黄金波动率{vol*100:.1f}%偏高+Z-score={zscore:.1f}→短期过热→回调风险",
                holding_days=5, stop_loss=-0.02, confidence=0.50,
                strength=-0.50, trigger="gold_overheated",
                volatility_20d=vol, zscore=zscore,
            )

        if zscore is not None and zscore <= -2.0:
            return self._make_signal(
                asset="黄金期货(AU)", direction="BUY",
                reason=f"黄金Z-score={zscore:.1f}，极端低位→避险资产超卖→反弹",
                holding_days=10, stop_loss=-0.03, confidence=0.55,
                strength=0.55, trigger="gold_extreme_low", zscore=zscore,
            )
        return None

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        zscore = data.get("zscore_20d")
        forex_change = data.get("forex_change_20d")
        tips_change = data.get("tips_change")
        if zscore is None:
            return 0.0
        strength = zscore / 3.0
        if forex_change is not None and forex_change > 0:
            strength += forex_change * 10
        if tips_change is not None and tips_change < 0:
            strength += abs(tips_change) * 20
        return max(-1.0, min(1.0, strength))