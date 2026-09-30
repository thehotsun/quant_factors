#!/usr/bin/env python
"""夜盘静默采样：对比「新浪 nf_」与「东财 push2」期货实时行情的时间戳/价格，
用于确认某个交易所（如大商所）的行情滞后是数据源常态、还是偶发。

只追加写入日志，不推送。由 crontab 在夜盘时段调用。

日志：data/realtime_source_probe.log
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.realtime_quote as rq  # noqa: E402

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "realtime_source_probe.log")


def _fmt(now: datetime, q) -> str:
    if not q:
        return "-"
    ts = q.get("ts")
    if ts:
        lag = (now - ts).total_seconds() / 60
        return f"{ts:%m-%d %H:%M:%S} lag={lag:.0f}m px={q.get('price')}"
    return f"ts=? px={q.get('price')}"


def main():
    symbols = list(rq._EM_SECIDS.keys())
    now = datetime.now()
    em = rq._fetch_eastmoney(symbols)
    sina = rq._fetch_sina(symbols)

    lines = [f"[{now:%Y-%m-%d %H:%M:%S}] 采样（sina=新浪 nf_，em=东财 push2）"]
    for s in symbols:
        lines.append(f"  {s:5} sina={_fmt(now, sina.get(s))}  |  em={_fmt(now, em.get(s))}")
    text = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
