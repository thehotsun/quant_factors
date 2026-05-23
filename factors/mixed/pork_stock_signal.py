"""生猪现货 + 期货 + 饲料成本 → 养殖ETF 混合信号因子

这是方案三的核心样板：驱动数据和交易标的分离。
驱动：生猪期货、玉米期货、豆粕期货、生猪现货（可选）
交易标的：养殖ETF(159865)

信号逻辑：
- 生猪价格处于周期低位 → BUY
- 饲料成本下降 → BUY
- 养殖ETF未明显破位 → 加分
- 生猪现货企稳/上涨 → 加分
- 生猪现货暴跌 → 减分
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from factors.mixed.base import MixedDriverFactor
from core.factor_registry import FactorRegistry


@FactorRegistry.register(
    name="pork_stock_signal",
    category="mixed",
    description="生猪现货+期货+饲料成本 → 养殖ETF买入信号",
    asset="养殖ETF(159865)",
    data_deps=["pork_futures", "corn_futures", "soybean_meal_futures"],
)
class PorkStockSignal(MixedDriverFactor):
    """混合信号因子：生猪产业链 → 养殖ETF"""

    def calculate(self) -> Dict[str, Any]:
        bundle = self.load_drivers()
        futures = bundle.get("futures", {})
        spot = bundle.get("spot", {})
        equity = bundle.get("equity", {})

        result: Dict[str, Any] = {
            "trade_asset": self.trade_asset,
            "trade_asset_type": self.trade_asset_type,
            "execution_asset": self.execution_asset,
            "pork_price": None, "pork_zscore": None, "pork_momentum_20d": None,
            "feed_cost_index": None, "feed_cost_change_20d": None,
            "equity_momentum_20d": None,
            "spot_price": None, "spot_change_5d": None,
            "factor_value": None, "factor_value_type": "score",
        }

        # --- Futures drivers ---
        pork_df = futures.get("pork_futures")
        corn_df = futures.get("corn_futures")
        meal_df = futures.get("soybean_meal_futures")

        if pork_df is not None and len(pork_df) >= 20:
            features = self._multi_window_features(pork_df)
            result["pork_price"] = features.get("current")
            result["pork_momentum_20d"] = features.get("change_20d")
            result["pork_zscore"] = self._rolling_zscore(
                features.get("current", 0), pork_df["close"]
            )

        # Feed cost: corn(60%) + soybean meal(25%) composite
        if corn_df is not None and meal_df is not None and len(corn_df) >= 20 and len(meal_df) >= 20:
            corn_price = float(corn_df["close"].iloc[-1])
            meal_price = float(meal_df["close"].iloc[-1])
            # Normalize to index: corn * 0.6 + meal * 0.25 (simplified)
            result["feed_cost_index"] = round(corn_price * 0.6 + meal_price * 0.25, 2)
            if len(corn_df) >= 20 and len(meal_df) >= 20:
                corn_20d_ago = float(corn_df["close"].iloc[-20])
                meal_20d_ago = float(meal_df["close"].iloc[-20])
                cost_now = corn_price * 0.6 + meal_price * 0.25
                cost_20d = corn_20d_ago * 0.6 + meal_20d_ago * 0.25
                if cost_20d > 0:
                    result["feed_cost_change_20d"] = round((cost_now - cost_20d) / cost_20d, 4)

        # --- Spot driver (optional) ---
        pork_spot_df = spot.get("pork_spot")
        if pork_spot_df is not None and len(pork_spot_df) >= 5:
            col = "value" if "value" in pork_spot_df.columns else "close"
            spot_price = float(pork_spot_df[col].iloc[-1])
            spot_5d_ago = float(pork_spot_df[col].iloc[-5])
            result["spot_price"] = spot_price
            if spot_5d_ago > 0:
                result["spot_change_5d"] = round((spot_price - spot_5d_ago) / spot_5d_ago, 4)

        # --- Equity driver (optional) ---
        equity_df = equity.get("breeding_etf")
        if equity_df is not None and len(equity_df) >= 20:
            features_eq = self._multi_window_features(equity_df)
            result["equity_momentum_20d"] = features_eq.get("change_20d")

        # Composite score
        score = self._compute_score(result)
        result["factor_value"] = score
        return result

    def _compute_score(self, data: Dict[str, Any]) -> float:
        """Compute composite signal score from -1.0 to +1.0."""
        score = 0.0
        weights = 0.0

        # Pork cycle position (weight: 0.35)
        z = data.get("pork_zscore")
        if z is not None:
            if z < -2.0:
                score += 0.35 * 1.0  # deep oversold
            elif z < -1.0:
                score += 0.35 * 0.5
            elif z > 2.0:
                score -= 0.35 * 1.0  # deep overbought
            elif z > 1.0:
                score -= 0.35 * 0.5
            weights += 0.35

        # Feed cost direction (weight: 0.25)
        fc = data.get("feed_cost_change_20d")
        if fc is not None:
            if fc < -0.05:
                score += 0.25 * 0.8  # cost dropping fast
            elif fc < 0:
                score += 0.25 * 0.3
            elif fc > 0.05:
                score -= 0.25 * 0.8  # cost rising fast
            elif fc > 0:
                score -= 0.25 * 0.3
            weights += 0.25

        # Equity momentum (weight: 0.2)
        eq_mom = data.get("equity_momentum_20d")
        if eq_mom is not None:
            if eq_mom > 0.05:
                score += 0.2 * 0.5
            elif eq_mom < -0.1:
                score -= 0.2 * 0.8  # ETF breaking down
            weights += 0.2

        # Spot confirmation (weight: 0.2)
        spot_chg = data.get("spot_change_5d")
        if spot_chg is not None:
            if spot_chg > 0.02:
                score += 0.2 * 0.7  # spot rising
            elif spot_chg < -0.03:
                score -= 0.2 * 0.7  # spot falling
            weights += 0.2

        if weights > 0:
            score = score / weights
        return round(max(-1.0, min(1.0, score)), 4)

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self._get_or_calculate()
        score = data.get("factor_value")
        if score is None:
            return None

        missing = self.get_missing_drivers()
        confidence_adj = 0.1 * len(missing)  # reduce confidence for missing drivers

        if score >= 0.3:
            return self._make_signal(
                direction="BUY",
                reason=self._build_reason(data, "BUY"),
                holding_days=20,
                stop_loss=self._volatility_stop_from_data(data) or -0.08,
                confidence=max(0.3, 0.65 - confidence_adj),
                strength=score,
                trigger="pork_cycle_bottom",
                factor_value=score,
            )
        elif score <= -0.3:
            return self._make_signal(
                direction="SELL",
                reason=self._build_reason(data, "SELL"),
                holding_days=10,
                stop_loss=-0.05,
                confidence=max(0.3, 0.55 - confidence_adj),
                strength=score,
                trigger="pork_cycle_top",
                factor_value=score,
            )
        return self._make_signal(
            direction="HOLD",
            reason="生猪价格和饲料成本未出现明确方向信号",
            confidence=0.4,
            strength=score,
            trigger="neutral",
            factor_value=score,
        )

    def _build_reason(self, data: Dict[str, Any], direction: str) -> str:
        parts = []
        if direction == "BUY":
            z = data.get("pork_zscore")
            if z is not None and z < -1.0:
                parts.append(f"生猪价格历史低位(z={z:.1f})")
            fc = data.get("feed_cost_change_20d")
            if fc is not None and fc < 0:
                parts.append(f"饲料成本下降{abs(fc)*100:.1f}%")
            spot = data.get("spot_change_5d")
            if spot is not None and spot > 0:
                parts.append("现货企稳回升")
        else:
            z = data.get("pork_zscore")
            if z is not None and z > 1.0:
                parts.append(f"生猪价格历史高位(z={z:.1f})")
            fc = data.get("feed_cost_change_20d")
            if fc is not None and fc > 0:
                parts.append(f"饲料成本上升{fc*100:.1f}%")
        missing = self.get_missing_drivers()
        if missing:
            parts.append(f"缺失数据: {','.join(missing)}")
        return "→".join(parts) if parts else "综合评分中性"

    def _volatility_stop_from_data(self, data: Dict[str, Any]) -> Optional[float]:
        """Estimate stop loss from pork volatility."""
        pork_price = data.get("pork_price")
        if pork_price is None:
            return None
        # Use a simple 8% stop for now; can be improved with actual vol data
        return -0.08

    def signal_strength(self) -> float:
        data = self._get_or_calculate()
        return data.get("factor_value") or 0.0
