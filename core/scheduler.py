"""Scheduler bootstrap helpers."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_scheduler_lock_fd = None


def init_scheduler(daily_data_refresh: Callable[[], None],
                   daily_data_refresh_foreign: Callable[[], None],
                   daily_ic_compute: Callable[[], None],
                   daily_push: Callable[[], None],
                   lock_path: str = "/tmp/quant_factors_scheduler.lock") -> bool:
    """Start APScheduler once across gunicorn workers.

    Returns True when the current process owns the scheduler lock and starts
    jobs, False when another worker already owns it.
    """
    import fcntl
    global _scheduler_lock_fd

    lock_fd = open(Path(lock_path), "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.info("另一个 worker 已持有调度器锁，跳过初始化")
        lock_fd.close()
        return False
    _scheduler_lock_fd = lock_fd

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.error("APScheduler 未安装，定时任务不可用。请执行: pip install apscheduler")
        raise SystemExit(1)

    scheduler = BackgroundScheduler(
        job_defaults={
            "misfire_grace_time": 7200,
            "coalesce": True,
            "max_instances": 1,
        }
    )
    scheduler.add_job(daily_data_refresh, "cron", hour=18, minute=0, id="daily_refresh")
    scheduler.add_job(daily_data_refresh_foreign, "cron", hour=6, minute=0, id="daily_refresh_foreign")
    scheduler.add_job(daily_ic_compute, "cron", hour=18, minute=30, id="daily_ic")
    scheduler.add_job(daily_push, "cron", hour=18, minute=35, id="daily_push")
    scheduler.start()
    logger.info(
        "APScheduler 已启动 (worker PID %d): 每日 18:00 国内数据刷新, 次日 06:00 外盘数据刷新, 18:30 IC 计算, 18:35 推送",
        os.getpid(),
    )
    return True
