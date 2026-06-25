#!/usr/bin/env python3
"""每日信号追踪器 — 记录全因子值 + 信号 + 跟踪价格。

每日 18:30 由 cron 调用，在 daily_data_refresh 之后运行。
对所有因子链（有 factor_module 的）执行：
  1. calculate() → factor_value
  2. signal() → direction / strength / reason
  3. 从 data_deps[0] 对应的 parquet 读当日收盘价 → entry_price
  4. 写入 signal_tracking 表

错误隔离：单个因子失败不影响其他因子。
"""

import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import load_chains_config, load_factor_params
from core.factor_runner import FactorRunner, extract_factor_value
from core.data_bus import DataBus
from core.signal_logger import SignalLogger
from evaluation.ic_monitor import ICMonitor

logging.basicConfig(level=logging.WARNING, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('daily_signal_tracker')

DATA_DIR = PROJECT_ROOT / 'data'
DB_PATH = DATA_DIR / 'signals.db'


def init_db(db_path: Path):
    """确保 signal_tracking 表存在。"""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factor_name TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            factor_value REAL,
            signal_direction TEXT,
            signal_strength REAL,
            signal_reason TEXT,
            asset TEXT,
            price_file TEXT,
            entry_price REAL,
            exit_price_1d REAL,
            exit_price_5d REAL,
            exit_price_10d REAL,
            return_1d REAL,
            return_5d REAL,
            return_10d REAL,
            hit_1d INTEGER,
            hit_5d INTEGER,
            hit_10d INTEGER,
            UNIQUE(factor_name, signal_date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tracking_factor
        ON signal_tracking(factor_name, signal_date)
    """)
    conn.commit()
    conn.close()


def get_entry_price(data_bus: DataBus, price_file: str) -> float | None:
    """从 parquet 文件读取最新收盘价。"""
    if not price_file:
        return None
    try:
        df = data_bus.get(price_file)
        if df is None or df.empty or 'close' not in df.columns:
            return None
        latest = df.dropna(subset=['close']).tail(1)
        if latest.empty:
            return None
        return float(latest['close'].iloc[0])
    except Exception:
        return None


def get_price_file(chains_config: dict, factor_name: str) -> str | None:
    """从 data_deps[0] 推断跟踪价格文件名。"""
    cfg = chains_config.get(factor_name, {})
    deps = cfg.get('data_deps', [])
    if not deps:
        return None
    return deps[0]


def track_factor(factor_name: str, chains_config: dict, runner: FactorRunner,
                 data_bus: DataBus, today: str) -> dict:
    """追踪单个因子，返回记录字典。"""
    cfg = chains_config.get(factor_name, {})
    trade_asset = cfg.get('trade_asset', cfg.get('asset', ''))
    price_file = get_price_file(chains_config, factor_name)

    # 计算因子值
    calc_result = runner.calculate_only(factor_name)
    factor_value = None
    if calc_result and not calc_result.get('error'):
        fd = calc_result.get('factor_data', {})
        factor_value = extract_factor_value(fd, factor_name)

    # 计算信号
    signal_direction = 'HOLD'
    signal_strength = 0.0
    signal_reason = None
    try:
        factor = runner.instantiate(factor_name)
        if factor:
            sig = factor.signal()
            if sig:
                signal_direction = sig.get('direction', 'HOLD')
                signal_strength = sig.get('strength', 0.0) or 0.0
                signal_reason = sig.get('reason')
    except Exception as e:
        logger.debug("因子 %s signal() 失败: %s", factor_name, e)

    # 获取跟踪价格
    entry_price = get_entry_price(data_bus, price_file)

    return {
        'factor_name': factor_name,
        'signal_date': today,
        'factor_value': factor_value,
        'signal_direction': signal_direction,
        'signal_strength': signal_strength,
        'signal_reason': signal_reason,
        'asset': trade_asset,
        'price_file': price_file,
        'entry_price': entry_price,
    }


def save_record(conn: sqlite3.Connection, record: dict):
    """INSERT OR REPLACE 一条记录。"""
    conn.execute("""
        INSERT OR REPLACE INTO signal_tracking
            (factor_name, signal_date, factor_value, signal_direction,
             signal_strength, signal_reason, asset, price_file, entry_price)
        VALUES (:factor_name, :signal_date, :factor_value, :signal_direction,
                :signal_strength, :signal_reason, :asset, :price_file, :entry_price)
    """, record)


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"{'='*60}")
    print(f"每日信号追踪 | {today}")
    print(f"{'='*60}")

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

    # 初始化数据库
    init_db(DB_PATH)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    # 获取因子列表（只处理有 factor_module 的）
    factor_names = [
        name for name, cfg in chains_config.items()
        if cfg.get('factor_module')
    ]

    ok_count = 0
    signal_count = 0
    error_count = 0

    for name in sorted(factor_names):
        try:
            record = track_factor(name, chains_config, runner, data_bus, today)
            save_record(conn, record)
            ok_count += 1

            if record['signal_direction'] != 'HOLD':
                signal_count += 1
                print(f"  📊 {name:30s} | {record['signal_direction']:4s} | "
                      f"fv={record['factor_value'] or '-':>10} | "
                      f"price={record['entry_price'] or '-'}")
            else:
                fv_str = f"{record['factor_value']:.2f}" if record['factor_value'] is not None else '-'
                print(f"  {name:30s} | HOLD | fv={fv_str:>10s}")

        except Exception as e:
            error_count += 1
            logger.error("因子 %s 追踪失败: %s", name, e)
            print(f"  ❌ {name:30s} | ERROR: {e}")

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"完成: {ok_count}/{len(factor_names)} 成功, "
          f"{signal_count} 个信号, {error_count} 个失败")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
