"""Network guards: default request timeouts and hard job timeouts.

Background
----------
On 2026-09-18 the daily domestic data refresh stalled forever on an outbound
HTTPS call that had **no timeout** (``pd.read_csv(url)`` against FRED). Because
APScheduler runs the job with ``max_instances=1``, the stuck job kept occupying
the single slot and every following day's run was silently skipped, freezing all
domestic data for 10 days.

This module provides two independent safety nets:

1. :func:`install_requests_timeout` — injects a sane default timeout into every
   ``requests`` call (akshare / pandas URL readers included) so a stalled
   connection raises instead of blocking forever.
2. :func:`run_with_timeout` — runs a job body in a watchdog thread so that even
   a hang that bypasses the timeout net still releases the scheduler slot.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_PATCHED = False


def install_requests_timeout(default_seconds: float = 30.0) -> None:
    """Patch ``requests`` so calls without an explicit timeout get one.

    akshare (and some pandas URL readers) issue ``requests`` calls with no
    timeout; a stalled connection then blocks the calling thread forever.
    Injecting a default timeout here fixes every call site without touching
    individual fetchers.
    """
    global _PATCHED
    if _PATCHED:
        return
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:
        logger.warning("requests 未安装，跳过超时补丁")
        return

    original_send = HTTPAdapter.send

    def send_with_timeout(self, request, **kwargs):  # noqa: ANN001
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = default_seconds
        return original_send(self, request, **kwargs)

    send_with_timeout._quant_default_timeout = default_seconds  # type: ignore[attr-defined]
    HTTPAdapter.send = send_with_timeout
    _PATCHED = True
    logger.info("已为 requests 安装默认超时: %ss", default_seconds)


def run_with_timeout(fn: Callable[[], Any], timeout_seconds: float,
                     name: str = "job") -> Optional[Any]:
    """Run ``fn`` in a daemon thread and give up after ``timeout_seconds``.

    Returns ``fn``'s return value, or ``None`` on timeout. If ``fn`` raises, the
    exception is re-raised in the caller. The watchdog guarantees that even a
    permanently hung job releases the APScheduler slot (``max_instances=1``), so
    a single bad network call can no longer freeze the daily schedule.
    """
    box: dict = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller
            box["error"] = exc
        finally:
            box["done"] = True

    worker = threading.Thread(target=_target, name=f"netguard-{name}", daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if not box.get("done"):
        logger.error("[watchdog] %s 超过 %ss 仍未结束，已放弃并释放调度槽位",
                     name, timeout_seconds)
        return None
    if "error" in box:
        raise box["error"]
    return box.get("value")
