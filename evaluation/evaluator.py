from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from scipy import stats


class FactorEvaluator:
    """因子评估器：IC/IR/分层回测"""

    @staticmethod
    def ic_analysis(factor_values: pd.Series, forward_returns: pd.Series,
                    method: str = "pearson") -> Dict[str, Any]:
        """IC分析：计算因子值与未来收益的相关性"""
        common_idx = factor_values.dropna().index.intersection(forward_returns.dropna().index)
        if len(common_idx) < 10:
            return {"error": "样本不足", "sample_size": len(common_idx)}

        fv = factor_values.loc[common_idx]
        fr = forward_returns.loc[common_idx]

        if method == "pearson":
            ic, p_value = stats.pearsonr(fv, fr)
        elif method == "spearman":
            ic, p_value = stats.spearmanr(fv, fr)
        else:
            ic, p_value = stats.pearsonr(fv, fr)

        return {
            "ic": round(float(ic), 4),
            "ic_p_value": round(float(p_value), 4),
            "ic_significant": p_value < 0.05,
            "sample_size": len(common_idx),
            "method": method,
        }

    @staticmethod
    def rolling_ic(factor_values: pd.Series, forward_returns: pd.Series,
                   window: int = 20, method: str = "pearson") -> pd.Series:
        """滚动IC序列"""
        common_idx = factor_values.dropna().index.intersection(forward_returns.dropna().index)
        fv = factor_values.loc[common_idx]
        fr = forward_returns.loc[common_idx]

        ic_series = pd.Series(index=common_idx, dtype=float)
        for i in range(window - 1, len(common_idx)):
            idx_slice = common_idx[i - window + 1:i + 1]
            if method == "pearson":
                ic, _ = stats.pearsonr(fv.loc[idx_slice], fr.loc[idx_slice])
            else:
                ic, _ = stats.spearmanr(fv.loc[idx_slice], fr.loc[idx_slice])
            ic_series.iloc[i] = ic

        return ic_series.dropna()

    @staticmethod
    def ir_analysis(ic_series: pd.Series) -> Dict[str, Any]:
        """IR分析：IC均值/IC标准差"""
        if len(ic_series) < 5:
            return {"error": "IC序列不足"}

        ic_mean = float(ic_series.mean())
        ic_std = float(ic_series.std())
        ir = ic_mean / ic_std if ic_std > 0 else 0.0

        return {
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(ic_std, 4),
            "ir": round(float(ir), 4),
            "ic_positive_ratio": round(float((ic_series > 0).mean()), 4),
            "sample_size": len(ic_series),
        }

    @staticmethod
    def stratified_backtest(factor_values: pd.Series, forward_returns: pd.Series,
                            n_groups: int = 5) -> Dict[str, Any]:
        """分层回测：按因子值分组，计算各组平均收益"""
        common_idx = factor_values.dropna().index.intersection(forward_returns.dropna().index)
        if len(common_idx) < n_groups * 3:
            return {"error": "样本不足", "sample_size": len(common_idx)}

        fv = factor_values.loc[common_idx]
        fr = forward_returns.loc[common_idx]

        df = pd.DataFrame({"factor": fv, "forward_return": fr})
        df["group"] = pd.qcut(df["factor"], n_groups, labels=False, duplicates="drop")

        group_returns = df.groupby("group")["forward_return"].mean()
        top_return = float(group_returns.iloc[-1]) if len(group_returns) > 0 else 0.0
        bottom_return = float(group_returns.iloc[0]) if len(group_returns) > 0 else 0.0
        spread = top_return - bottom_return

        return {
            "group_returns": {int(k): round(float(v), 6) for k, v in group_returns.items()},
            "top_group_return": round(top_return, 6),
            "bottom_group_return": round(bottom_return, 6),
            "long_short_spread": round(spread, 6),
            "n_groups": len(group_returns),
            "sample_size": len(common_idx),
        }

    @staticmethod
    def max_drawdown(returns: pd.Series) -> float:
        """最大回撤"""
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        return float(drawdown.min())

    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free: float = 0.02) -> float:
        """年化夏普比率"""
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free / 252
        if excess.std() == 0:
            return 0.0
        return float(excess.mean() / excess.std() * np.sqrt(252))

    @staticmethod
    def full_evaluation(factor_values: pd.Series, forward_returns: pd.Series,
                        n_groups: int = 5) -> Dict[str, Any]:
        """完整因子评估"""
        ic_result = FactorEvaluator.ic_analysis(factor_values, forward_returns)
        if "error" in ic_result:
            return ic_result

        rolling_ic = FactorEvaluator.rolling_ic(factor_values, forward_returns)
        ir_result = FactorEvaluator.ir_analysis(rolling_ic)
        stratified = FactorEvaluator.stratified_backtest(factor_values, forward_returns, n_groups)

        return {
            "ic_analysis": ic_result,
            "ir_analysis": ir_result,
            "stratified_backtest": stratified,
        }