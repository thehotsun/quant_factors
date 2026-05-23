"""通用商品→股票/ETF 混合信号模板因子

通过参数配置，一条因子代码可以复用到多个场景：
- 原油 → 中国石油
- 黄金 → 黄金ETF
- 铜 → 有色ETF
- 猪肉 → 养殖ETF

用法：在 chains.yaml 中配置 params 即可。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from factors.mixed.base import MixedDriverFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="commodity_to_equity",
    category="mixed",
    description="通用商品→股票/ETF混合信号模板",
    asset="通过params配置",
    data_deps=[],
)
class CommodityToEquitySignal(MixedDriverFactor):
    """通用商品→股票/ETF信号模板。

    params 配置示例:
    {
        "primary_commodity": "gold_futures",       # 主要商品驱动
        "cost_drivers": ["corn_futures"],          # 成本端驱动（可选）
        "valuation_metric": "zscore",              # 估值方法: zscore / percentile / momentum
        "valuation_window": 250,                   # 估值窗口
        "momentum_window": 20,                     # 动量窗口
        "buy_threshold": -1.5,                     # 买入阈值
        "sell_threshold": 1.5,                     # 卖出阈值
        "cost_weight": 0.3,                        # 成本端权重
        "commodity_weight": 0.5,                   # 商品端权重
        "equity_weight": 0.2,                      # 权益端权重
    }
    """

    def calculate(self) -> Dict[str, Any]:
        bundle = self.load_drivers()
        futures = bundle.get("futures", {})
        spot = bundle.get("spot", {})
        equity = bundle.get("equity", {})

        params = self.params or {}
        primary = params.get("primary_commodity", "")
        cost_drivers = params.get("cost_drivers", [])
        valuation = params.get("valuation_metric", "zscore")
        val_window = params.get("valuation_window", 250)
        mom_window = params.get("momentum_window", 20)

        result: Dict[str, Any] = {
            "trade_asset": self.trade_asset,
            "trade_asset_type": self.trade_asset_type,
            "execution_asset": self.execution_asset,
            "primary_commodity": primary,
            "commodity_signal": None,
            "cost_signal": None,
            "equity_signal": None,
            "factor_value": None,
            "factor_value_type": "score",
        }

        # --- Primary commodity signal ---
        commodity_df = futures.get(primary) or self.load(primary)
        if commodity_df is not None and len(commodity_df) >= val_window:
            current = float(commodity_df["close"].iloc[-1])
            if valuation == "zscore":
                result["commodity_signal"] = self._rolling_zscore(
                    current, commodity_df["close"].tail(val_window)
                )
            elif valuation == "percentile":
                result["commodity_signal"] = self._rolling_percentile(
                    current, commodity_df["close"].tail(val_window)
                ) / 100.0
            else:
                # momentum
                if len(commodity_df) >= mom_window:
                    past = float(commodity_df["close"].iloc[-mom_window])
                    result["commodity_signal"] = (current - past) / past if past != 0 else 0

            result["commodity_price"] = current

        # --- Cost drivers ---
        if cost_drivers:
            cost_signals = []
            for cd_name in cost_drivers:
                cd_df = futures.get(cd_name) or self.load(cd_name)
                if cd_df is not None and len(cd_df) >= mom_window:
                    current_cd = float(cd_df["close"].iloc[-1])
                    past_cd = float(cd_df["close"].iloc[-mom_window])
                    if past_cd != 0:
                        cost_signals.append((current_cd - past_cd) / past_cd)
            if cost_signals:
                result["cost_signal"] = sum(cost_signals) / len(cost_signals)

        # --- Equity signal ---
        # Find first equity driver
        equity_df = None
        for eq_name, eq_data in equity.items():
            if eq_data is not None:
                equity_df = eq_data
                break
        if equity_df is not None and len(equity_df) >= mom_window:
            current_eq = float(equity_df["close"].iloc[-1])
            past_eq = float(equity_df["close"].iloc[-mom_window])
            if past_eq != 0:
                result["equity_signal"] = (current_eq - past_eq) / past_eq

        # --- Composite score ---
        result["factor_value"] = self._compute_score(result)
        return result

    def _compute_score(self, data: Dict[str, Any]) -> float:
        params = self.params or {}
        buy_threshold = params.get("buy_threshold", -1.5)
        sell_threshold = params.get("sell_threshold", 1.5)
        c_weight = params.get("commodity_weight", 0.5)
        cost_weight = params.get("cost_weight", 0.3)
        e_weight = params.get("equity_weight", 0.2)

        score = 0.0
        weights = 0.0

        cs = data.get("commodity_signal")
        if cs is not None:
            if cs <= buy_threshold:
                score += c_weight * 1.0
            elif cs >= sell_threshold:
                score -= c_weight * 1.0
            else:
                # Linear interpolation
                score += c_weight * (-cs / max(abs(buy_threshold), abs(sell_threshold)))
            weights += c_weight

        cost_s = data.get("cost_signal")
        if cost_s is not None:
            if cost_s < -0.05:
                score += cost_weight * 0.7
            elif cost_s > 0.05:
                score -= cost_weight * 0.7
            weights += cost_weight

        eq_s = data.get("equity_signal")
        if eq_s is not None:
            if eq_s > 0.05:
                score += e_weight * 0.5
            elif eq_s < -0.1:
                score -= e_weight * 0.8
            weights += e_weight

        if weights > 0:
            score = score / weights
        return round(max(-1.0, min(1.0, score)), 4)

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        score = data.get("factor_value")
        if score is None:
            return None

        missing = self.get_missing_drivers()
        confidence_adj = 0.1 * len(missing)

        if score >= 0.3:
            return self._make_signal(
                direction="BUY",
                reason=self._build_reason(data, "BUY"),
                holding_days=20,
                stop_loss=-0.08,
                confidence=max(0.3, 0.6 - confidence_adj),
                strength=score,
                trigger="commodity_equity_buy",
                factor_value=score,
            )
        elif score <= -0.3:
            return self._make_signal(
                direction="SELL",
                reason=self._build_reason(data, "SELL"),
                holding_days=10,
                stop_loss=-0.05,
                confidence=max(0.3, 0.5 - confidence_adj),
                strength=score,
                trigger="commodity_equity_sell",
                factor_value=score,
            )
        return None

    def _build_reason(self, data: Dict[str, Any], direction: str) -> str:
        parts = []
        primary = data.get("primary_commodity", "commodity")
        cs = data.get("commodity_signal")
        if cs is not None:
            if direction == "BUY" and cs < 0:
                parts.append(f"{primary}估值偏低({cs:.2f})")
            elif direction == "SELL" and cs > 0:
                parts.append(f"{primary}估值偏高({cs:.2f})")
        missing = self.get_missing_drivers()
        if missing:
            parts.append(f"缺失: {','.join(missing)}")
        return "→".join(parts) if parts else f"{direction} {self.trade_asset}"

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        return data.get("factor_value") or 0.0
