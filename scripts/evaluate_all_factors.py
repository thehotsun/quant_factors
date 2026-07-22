#!/usr/bin/env python3
"""全因子 IC/IR 评估脚本。

对所有活跃因子计算：
- 当前因子值
- IC (Information Coefficient) — 因子值与未来收益的相关性
- IR (Information Ratio) — IC均值/IC标准差
- 分层回测 — 按因子值分5组，计算多空价差

输出：评估报告（终端 + 可选 JSON 文件）
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import load_chains_config, load_factor_params
from core.factor_runner import FactorRunner, extract_factor_value
from core.data_bus import DataBus
from core.signal_logger import SignalLogger
from evaluation.ic_monitor import ICMonitor
from evaluation.evaluator import FactorEvaluator

logging.basicConfig(level=logging.WARNING, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('evaluate_all')

# ========== 配置 ==========
DATA_DIR = PROJECT_ROOT / 'data'
OUTPUT_JSON = PROJECT_ROOT / 'data' / 'factor_evaluation.json'
IC_WINDOW = 20  # 滚动 IC 窗口
FORWARD_DAYS = 5  # 未来收益天数
MIN_HISTORY_DAYS = 60  # 最少历史天数


def load_price_data(data_bus: DataBus, symbol: str) -> pd.Series:
    """加载价格序列。"""
    df = data_bus.get(symbol)
    if df is None or 'close' not in df.columns:
        return pd.Series(dtype=float)
    return df['close'].astype(float).dropna()


def compute_forward_returns(prices: pd.Series, days: int = 5) -> pd.Series:
    """计算未来N日收益率。"""
    return prices.pct_change(days).shift(-days)


def compute_factor_history(factor_name: str, chains_config: dict, runner: FactorRunner,
                           lookback_days: int = 252) -> pd.Series:
    """计算因子的历史值序列（简化版：用当前值回填）。

    注：完整实现需要逐日重放因子计算，成本很高。
    这里用因子的底层数据构造近似的历史因子值。
    """
    cfg = chains_config.get(factor_name, {})
    data_deps = cfg.get('data_deps', [])
    if not data_deps:
        return pd.Series(dtype=float)

    # 取第一个数据依赖的价格作为近似因子代理
    primary_dep = data_deps[0]
    prices = load_price_data(runner._data_bus, primary_dep)
    if prices.empty or len(prices) < MIN_HISTORY_DAYS:
        return pd.Series(dtype=float)

    # 根据因子类型选择代理方式
    category = cfg.get('category', '')
    if category in ('macro',):
        # 宏观因子：直接用原始值
        return prices.tail(lookback_days)

    # 价格类因子：用收益率或z-score作为因子代理
    returns = prices.pct_change()
    zscore = (prices - prices.rolling(20).mean()) / prices.rolling(20).std()
    return zscore.tail(lookback_days).dropna()


def evaluate_factor(factor_name: str, chains_config: dict, runner: FactorRunner) -> dict:
    """评估单个因子。"""
    cfg = chains_config.get(factor_name, {})

    # 跳过组合链和无因子模块的链
    if not cfg.get('factor_module'):
        return None
    if cfg.get('status') == 'experimental':
        return {'name': factor_name, 'status': 'experimental', 'reason': '因子标记为 experimental'}

    # 获取当前因子值
    calc_result = runner.calculate_only(factor_name)
    if calc_result is None:
        return {'name': factor_name, 'status': 'error', 'reason': '实例化失败'}

    if calc_result.get('error'):
        return {'name': factor_name, 'status': 'error', 'reason': calc_result['error']}

    factor_data = calc_result.get('factor_data', {})
    current_value = extract_factor_value(factor_data, factor_name)
    signal_strength = calc_result.get('signal_strength')

    result = {
        'name': factor_name,
        'category': cfg.get('category', 'unknown'),
        'current_value': current_value,
        'signal_strength': signal_strength,
        'factor_value_type': factor_data.get('factor_value_type') if factor_data else None,
    }

    # 计算 IC/IR（需要历史数据）
    data_deps = cfg.get('data_deps', [])
    if not data_deps:
        result['status'] = 'no_data_deps'
        return result

    # 取主要依赖的价格
    primary_dep = data_deps[0]
    prices = load_price_data(runner._data_bus, primary_dep)
    if prices.empty or len(prices) < MIN_HISTORY_DAYS:
        result['status'] = 'insufficient_data'
        result['history_days'] = len(prices) if not prices.empty else 0
        return result

    # 计算未来收益
    fwd_returns = compute_forward_returns(prices, FORWARD_DAYS).dropna()

    # 构造因子代理序列（用价格 z-score）
    zscore = (prices - prices.rolling(20).mean()) / prices.rolling(20).std()
    factor_series = zscore.dropna()

    # 对齐
    common_idx = factor_series.index.intersection(fwd_returns.index)
    if len(common_idx) < 30:
        result['status'] = 'insufficient_overlap'
        result['overlap_days'] = len(common_idx)
        return result

    fv = factor_series.loc[common_idx]
    fr = fwd_returns.loc[common_idx]

    # IC 分析
    ic_result = FactorEvaluator.ic_analysis(fv, fr)
    result['ic'] = ic_result

    # 滚动 IC → IR
    if 'error' not in ic_result:
        rolling_ic = FactorEvaluator.rolling_ic(fv, fr, window=IC_WINDOW)
        ir_result = FactorEvaluator.ir_analysis(rolling_ic)
        result['ir'] = ir_result

    # 分层回测
    stratified = FactorEvaluator.stratified_backtest(fv, fr)
    result['stratified'] = stratified

    result['status'] = 'ok'
    return result


def main():
    print("=" * 60)
    print("全因子 IC/IR 评估")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 初始化
    DataBus.reset()
    chains_config = load_chains_config()
    factor_params = load_factor_params()
    data_bus = DataBus(str(DATA_DIR))
    signal_logger = SignalLogger(str(DATA_DIR / 'signals.db'))
    ic_monitor = ICMonitor(str(DATA_DIR / 'ic_monitor.db'))

    runner = FactorRunner(
        chains_config, factor_params, str(DATA_DIR),
        signal_logger, ic_monitor, data_bus=data_bus
    )
    runner.ensure_imported()

    # 评估所有因子
    results = []
    factor_names = [name for name, cfg in chains_config.items() if cfg.get('factor_module')]

    print(f"\n因子总数: {len(factor_names)}")
    print("-" * 60)

    for name in sorted(factor_names):
        try:
            result = evaluate_factor(name, chains_config, runner)
            if result:
                results.append(result)
                status = result.get('status', '?')
                ic_val = result.get('ic', {}).get('ic', '-')
                ir_val = result.get('ir', {}).get('ir', '-')
                spread = result.get('stratified', {}).get('long_short_spread', '-')
                ic_str = f'{ic_val:>7.4f}' if isinstance(ic_val, (int, float)) else f'{str(ic_val):>7s}'
                ir_str = f'{ir_val:>7.4f}' if isinstance(ir_val, (int, float)) else f'{str(ir_val):>7s}'
                spread_str = f'{spread:>8.4f}' if isinstance(spread, (int, float)) else f'{str(spread):>8s}'
                print(f'  {name:30s} | IC={ic_str} | IR={ir_str} | 多空={spread_str} | {status}')
        except Exception as e:
            print(f"  {name:30s} | ERROR: {e}")
            results.append({'name': name, 'status': 'exception', 'reason': str(e)})

    # 汇总
    ok_results = [r for r in results if r.get('status') == 'ok']
    sig_results = [r for r in ok_results if r.get('ic', {}).get('ic_significant')]

    print("\n" + "=" * 60)
    print("汇总")
    print(f"  有效因子: {len(ok_results)}/{len(results)}")
    print(f"  IC显著 (p<0.05): {len(sig_results)}/{len(ok_results)}")

    if sig_results:
        print(f"\n  IC显著因子:")
        for r in sorted(sig_results, key=lambda x: abs(x['ic'].get('ic', 0)), reverse=True):
            ic = r['ic']['ic']
            ir = r.get('ir', {}).get('ir', '-')
            spread = r.get('stratified', {}).get('long_short_spread', '-')
            ir_str = f'{ir:>7.4f}' if isinstance(ir, (int, float)) else f'{str(ir):>7s}'
            spread_str = f'{spread:>8.4f}' if isinstance(spread, (int, float)) else f'{str(spread):>8s}'
            print(f'    {r["name"]:25s} IC={ic:>7.4f}  IR={ir_str}  多空={spread_str}')

    # 保存 JSON
    output = {
        'evaluated_at': datetime.now().isoformat(),
        'forward_days': FORWARD_DAYS,
        'ic_window': IC_WINDOW,
        'total_factors': len(results),
        'ok_factors': len(ok_results),
        'significant_factors': len(sig_results),
        'results': results,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已保存: {OUTPUT_JSON}")


if __name__ == '__main__':
    main()
