"""交易数据获取健康巡检（默认每周一次）。

补足每日 19:00「新鲜度巡检」看不到的盲区：抓取是否成功、刷新任务是否被静默跳过
（如 2026-10-10 那次外盘数据停在 9/30 却无人知晓）。

体检三件事：
  1) 写盘新鲜度  —— parquet 最新日期 vs 阈值（复用 check_data_freshness）
  2) 源链可达性  —— 逐个数据集、逐个源能否抓、抓到几号（复用 source_chain.probe_all）
  3) 刷新任务台账 —— refresh_manifest：上次结束时间、failed/skipped 情况

产出 ``data/health_audit.json``；仅在发现问题时推送（否则静默），避免日常噪音。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.settings import DATA_DIR, REFRESH_MANIFEST_PATH

logger = logging.getLogger(__name__)

AUDIT_PATH = Path(DATA_DIR) / "health_audit.json"


def _audit_freshness() -> List[str]:
    """写盘新鲜度：仅看 parquet 最新日期（源/清单由本模块另查，避免重复）。"""
    from core.data_refresh import check_data_freshness
    return check_data_freshness(push=False, include_status=False, include_manifest=False)


def _run_with_timeout(fn, timeout: float):
    """兼容旧引用：改用 source_chain 的统一超时封装。"""
    from core.source_chain import run_with_timeout
    return run_with_timeout(fn, timeout)


def _audit_sources(probe: bool, timeout: float = 120.0) -> Dict[str, Any]:
    """源链状态：probe=True 时现场探测每个源；否则读最近一次落盘状态。

    探测在 daemon 线程跑并加硬超时，避免某些无超时的抓取器（akshare）卡死阻塞调度线程。
    """
    from core.source_chain import probe_all, read_status
    if not probe:
        return (read_status().get("datasets") or {})
    return _run_with_timeout(probe_all, timeout)


def _audit_manifest() -> Dict[str, Any]:
    """刷新任务台账：上次结束时间、失败项、汇总。"""
    p = Path(REFRESH_MANIFEST_PATH)
    if not p.exists():
        return {"present": False}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"present": True, "error": str(e)}

    summary = payload.get("summary") or {}
    ended = payload.get("ended_at")
    lag_hours = None
    if ended:
        try:
            lag_hours = (datetime.now() - datetime.fromisoformat(ended)).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            pass
    failed_items = [r.get("name") for r in payload.get("records", [])
                    if r.get("status") == "failed"]
    return {
        "present": True,
        "job": payload.get("job"),
        "ended_at": ended,
        "lag_hours": round(lag_hours, 1) if lag_hours is not None else None,
        "summary": summary,
        "failed_items": failed_items,
    }


def run_health_audit(push: bool = True, *, probe: bool = True,
                     today: Optional[date] = None) -> Dict[str, Any]:
    """执行一次健康巡检，返回报告 dict（并落盘 + 异常时推送）。"""
    problems: List[str] = []

    # ① 先探测源链（会刷新 source_status.json，也供 /sources 接口复用）
    probe_error = None
    try:
        sources = _audit_sources(probe)
    except Exception as e:  # noqa: BLE001
        sources = {}
        probe_error = f"源链探测失败/超时: {e}"

    # ② 写盘新鲜度（纯 parquet 日期；源/清单另查，避免重复）
    freshness = _audit_freshness()
    problems.extend(freshness)
    if probe_error:
        problems.append(probe_error)

    # ③ 源链可达性
    for key, st in (sources or {}).items():
        label = st.get("label", key)
        if not st.get("ok", True):
            srcs = "、".join(s.get("source", "?") for s in st.get("sources", []))
            problems.append(f"{label}: 所有源均不可用/不新鲜（{srcs}）")

    # ④ 刷新任务台账
    manifest = _audit_manifest()
    if not manifest.get("present"):
        problems.append("刷新清单缺失（refresh_manifest.json 不存在）")
    else:
        if manifest.get("failed_items"):
            problems.append(f"刷新任务失败项: {'、'.join(manifest['failed_items'])}")
        lag = manifest.get("lag_hours")
        if lag is not None and lag > 72:
            problems.append(f"刷新任务: 上次结束于 {manifest.get('ended_at')}（{lag:.0f} 小时前）")

    report: Dict[str, Any] = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "ok": not problems,
        "problems": problems,
        "freshness": freshness,
        "sources": sources,
        "manifest": manifest,
    }

    # 落盘
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = AUDIT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(AUDIT_PATH)
    except Exception as e:  # noqa: BLE001
        logger.warning("写 health_audit.json 失败: %s", e)

    if problems:
        detail = "\n".join(f"- {p}" for p in problems)
        logger.warning("健康巡检发现 %d 项异常\n%s", len(problems), detail)
        if push:
            try:
                from core.push import get_push_manager
                get_push_manager().send(
                    "量化系统健康巡检：发现异常",
                    f"⚠️ **交易数据健康巡检**（{len(problems)} 项异常）\n" + detail,
                )
            except Exception as e:  # noqa: BLE001
                logger.error("健康巡检推送失败: %s", e)
    else:
        logger.info("健康巡检通过：数据新鲜、源链可达、刷新任务正常")

    return report
