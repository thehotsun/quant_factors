#!/usr/bin/env python3
"""信号回看脚本 — 回填收益 + 生成业绩报告。

手动运行，执行两步：
  1. 回填：查找 exit_price 未填充的记录，从 parquet 读取对应日期收盘价
  2. 报告：按因子汇总命中率、平均收益、信号频次

用法：
  python scripts/signal_review.py            # 回填 + 报告
  python scripts/signal_review.py --report   # 只出报告（不回填）
"""

import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / 'data'
DB_PATH = DATA_DIR / 'signals.db'


def get_price_on_date(price_file: str, target_date: str) -> float | None:
    """从 parquet 读取指定日期的收盘价。"""
    path = DATA_DIR / f"{price_file}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if 'close' not in df.columns or 'date' not in df.columns:
            return None
        df['date'] = pd.to_datetime(df['date'])
        target = pd.to_datetime(target_date)
        row = df[df['date'] == target]
        if row.empty:
            return None
        return float(row['close'].iloc[0])
    except Exception:
        return None


def get_price_n_days_later(price_file: str, signal_date: str, n: int) -> float | None:
    """获取信号日后第 N 个交易日的收盘价。"""
    path = DATA_DIR / f"{price_file}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if 'close' not in df.columns or 'date' not in df.columns:
            return None
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        target = pd.to_datetime(signal_date)
        # 找到信号日的位置
        idx = df[df['date'] == target].index
        if len(idx) == 0:
            # 找最近的交易日
            mask = df['date'] >= target
            if not mask.any():
                return None
            idx = df[mask].index[0:1]
        pos = idx[0] + n
        if pos >= len(df):
            return None
        return float(df.iloc[pos]['close'])
    except Exception:
        return None


def backfill(conn: sqlite3.Connection):
    """回填 exit_price 和 return。"""
    cursor = conn.execute("""
        SELECT id, factor_name, signal_date, signal_direction, entry_price, price_file
        FROM signal_tracking
        WHERE exit_price_1d IS NULL
          AND signal_direction != 'HOLD'
          AND price_file IS NOT NULL
          AND entry_price IS NOT NULL
    """)
    rows = cursor.fetchall()

    if not rows:
        print("无需回填的记录。")
        return 0

    filled = 0
    for row_id, factor_name, signal_date, direction, entry_price, price_file in rows:
        p1 = get_price_n_days_later(price_file, signal_date, 1)
        p5 = get_price_n_days_later(price_file, signal_date, 5)
        p10 = get_price_n_days_later(price_file, signal_date, 10)

        if p1 is None and p5 is None and p10 is None:
            continue

        r1 = (p1 - entry_price) / entry_price if p1 and entry_price else None
        r5 = (p5 - entry_price) / entry_price if p5 and entry_price else None
        r10 = (p10 - entry_price) / entry_price if p10 and entry_price else None

        # 计算 hit: BUY → 价格涨=hit, SELL → 价格跌=hit
        def calc_hit(ret):
            if ret is None or direction == 'HOLD':
                return None
            if direction == 'BUY':
                return 1 if ret > 0 else 0
            elif direction == 'SELL':
                return 1 if ret < 0 else 0
            return None

        conn.execute("""
            UPDATE signal_tracking
            SET exit_price_1d = ?, exit_price_5d = ?, exit_price_10d = ?,
                return_1d = ?, return_5d = ?, return_10d = ?,
                hit_1d = ?, hit_5d = ?, hit_10d = ?
            WHERE id = ?
        """, (p1, p5, p10, r1, r5, r10, calc_hit(r1), calc_hit(r5), calc_hit(r10), row_id))
        filled += 1

    conn.commit()
    print(f"回填完成: {filled}/{len(rows)} 条记录。")
    return filled


def generate_report(conn: sqlite3.Connection):
    """生成业绩报告。"""
    # 获取所有有信号的因子
    cursor = conn.execute("""
        SELECT factor_name,
               COUNT(*) as total_signals,
               SUM(CASE WHEN signal_direction != 'HOLD' THEN 1 ELSE 0 END) as active_signals,
               SUM(CASE WHEN signal_direction = 'BUY' THEN 1 ELSE 0 END) as buy_signals,
               SUM(CASE WHEN signal_direction = 'SELL' THEN 1 ELSE 0 END) as sell_signals,
               SUM(CASE WHEN hit_1d = 1 THEN 1 ELSE 0 END) as hit_1d,
               SUM(CASE WHEN hit_1d IS NOT NULL AND signal_direction != 'HOLD' THEN 1 ELSE 0 END) as evaluable_1d,
               SUM(CASE WHEN hit_5d = 1 THEN 1 ELSE 0 END) as hit_5d,
               SUM(CASE WHEN hit_5d IS NOT NULL AND signal_direction != 'HOLD' THEN 1 ELSE 0 END) as evaluable_5d,
               SUM(CASE WHEN hit_10d = 1 THEN 1 ELSE 0 END) as hit_10d,
               SUM(CASE WHEN hit_10d IS NOT NULL AND signal_direction != 'HOLD' THEN 1 ELSE 0 END) as evaluable_10d,
               AVG(CASE WHEN signal_direction != 'HOLD' THEN return_1d END) as avg_return_1d,
               AVG(CASE WHEN signal_direction != 'HOLD' THEN return_5d END) as avg_return_5d,
               AVG(CASE WHEN signal_direction != 'HOLD' THEN return_10d END) as avg_return_10d
        FROM signal_tracking
        GROUP BY factor_name
        ORDER BY active_signals DESC
    """)
    rows = cursor.fetchall()

    if not rows:
        print("暂无数据。请先运行 daily_signal_tracker.py 积累数据。")
        return

    # 记录天数
    cursor2 = conn.execute("SELECT COUNT(DISTINCT signal_date) FROM signal_tracking")
    total_days = cursor2.fetchone()[0]

    print(f"\n{'='*80}")
    print(f"信号追踪业绩报告 | 数据天数: {total_days} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    # 表头
    print(f"\n{'因子':30s} | {'信号':>4s} | {'BUY':>4s} | {'SELL':>4s} | "
          f"{'1日命中':>7s} | {'5日命中':>7s} | {'10日命中':>8s} | "
          f"{'1日均收益':>8s} | {'5日均收益':>8s} | {'10日均收益':>9s}")
    print("-" * 130)

    for row in rows:
        (name, total, active, buys, sells,
         h1, e1, h5, e5, h10, e10,
         ar1, ar5, ar10) = row

        hit1_str = f"{h1}/{e1}" if e1 > 0 else "-"
        hit5_str = f"{h5}/{e5}" if e5 > 0 else "-"
        hit10_str = f"{h10}/{e10}" if e10 > 0 else "-"

        hit1_pct = f"{h1/e1*100:.0f}%" if e1 > 0 else "-"
        hit5_pct = f"{h5/e5*100:.0f}%" if e5 > 0 else "-"
        hit10_pct = f"{h10/e10*100:.0f}%" if e10 > 0 else "-"

        ar1_str = f"{ar1*100:+.2f}%" if ar1 is not None else "-"
        ar5_str = f"{ar5*100:+.2f}%" if ar5 is not None else "-"
        ar10_str = f"{ar10*100:+.2f}%" if ar10 is not None else "-"

        print(f"{name:30s} | {active:>4d} | {buys:>4d} | {sells:>4d} | "
              f"{hit1_pct:>7s} | {hit5_pct:>7s} | {hit10_pct:>8s} | "
              f"{ar1_str:>8s} | {ar5_str:>8s} | {ar10_str:>9s}")

    # 汇总
    cursor3 = conn.execute("""
        SELECT
            SUM(CASE WHEN hit_1d = 1 THEN 1 ELSE 0 END) as total_hit_1d,
            SUM(CASE WHEN hit_1d IS NOT NULL AND signal_direction != 'HOLD' THEN 1 ELSE 0 END) as total_eval_1d,
            SUM(CASE WHEN hit_5d = 1 THEN 1 ELSE 0 END) as total_hit_5d,
            SUM(CASE WHEN hit_5d IS NOT NULL AND signal_direction != 'HOLD' THEN 1 ELSE 0 END) as total_eval_5d
        FROM signal_tracking
    """)
    th1, te1, th5, te5 = cursor3.fetchone()

    print("-" * 130)
    if te1 and te1 > 0:
        print(f"{'汇总':30s} | {'':>4s} | {'':>4s} | {'':>4s} | "
              f"{th1}/{te1}={th1/te1*100:.0f}% | "
              f"{th5}/{te5}={th5/te5*100:.0f}% | {'':>8s} | {'':>8s} | {'':>8s} | {'':>9s}")

    print(f"\n{'='*80}")


def main():
    parser = argparse.ArgumentParser(description='信号回看脚本')
    parser.add_argument('--report', action='store_true', help='只出报告，不回填')
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        print("请先运行 daily_signal_tracker.py 积累数据。")
        return

    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    if not args.report:
        backfill(conn)

    generate_report(conn)
    conn.close()


if __name__ == '__main__':
    main()
