"""数据源容灾引擎：有序「源链」+ 新鲜度门 + 状态落盘。

设计（对应 config/data_sources.yaml）：
- 每个数据集配置一条有序源链（主源 → 备用 …）。
- `resolve_dataset` 按序尝试，取第一个「抓取成功 + 非空 + 新鲜」的结果；
  全部失败返回 None（调用方据此保留旧数据，不覆盖）。
- 每次尝试写入 data/source_status.json，供 `GET /sources` 查看「哪几个源能通」。
- `probe_all` 无条件探测链上**每一个**源（不做 failover），用于体检。

「新鲜」定义：DataFrame 最新日期距今天数 ≤ max_lag_days。这能识别
「接口成功但数据陈旧」（例如 FRED 返回旧值）——旧的 first_valid_frame 只看非空，
会误判为有效并覆盖写盘。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from core.settings import CONFIG_DIR, DATA_DIR, load_yaml

logger = logging.getLogger(__name__)

SOURCE_CONFIG_PATH = CONFIG_DIR / "data_sources.yaml"
STATUS_PATH = DATA_DIR / "source_status.json"


# ── 抓取器注册表（name -> callable(**args) -> DataFrame|None）────────────
def _f_sina_foreign_hist(symbol: str = "OIL"):
    from data_sources.foreign import fetch_sina_foreign_hist
    return fetch_sina_foreign_hist(symbol)


def _f_fred(series_id: str, name: Optional[str] = None, start_date: str = "2020-01-01"):
    from core.data_refresh import fetch_fred_csv
    return fetch_fred_csv(series_id, name or series_id, start_date)


def _f_boc_usd_cny():
    from data_sources.foreign import fetch_boc_usd_cny
    return fetch_boc_usd_cny()


def _f_eia_crude_stock():
    from data_sources.eia import fetch_eia_crude_stock
    return fetch_eia_crude_stock()


def _f_akshare_eia_crude_rate():
    import akshare as ak
    df = ak.macro_usa_eia_crude_rate()
    if df is None or df.empty:
        return None
    df = df.rename(columns={"日期": "date", "今值": "close"})
    if "date" not in df.columns or "close" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return df[["date", "close"]]


def _f_akshare_qvix():
    import akshare as ak
    return ak.index_option_300etf_qvix()


FETCHERS: Dict[str, Callable[..., Optional[pd.DataFrame]]] = {
    "sina_foreign_hist": _f_sina_foreign_hist,
    "fred": _f_fred,
    "boc_usd_cny": _f_boc_usd_cny,
    "eia_crude_stock": _f_eia_crude_stock,
    "akshare_eia_crude_rate": _f_akshare_eia_crude_rate,
    "akshare_qvix": _f_akshare_qvix,
}


def load_source_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载源链配置；失败返回空配置（不抛异常）。"""
    path = path or SOURCE_CONFIG_PATH
    try:
        cfg = load_yaml(path)
    except Exception as e:  # noqa: BLE001
        logger.warning("加载 data_sources.yaml 失败: %s", e)
        return {"defaults": {}, "datasets": {}}
    cfg.setdefault("defaults", {})
    cfg.setdefault("datasets", {})
    return cfg


def _last_date(df: Optional[pd.DataFrame]) -> Optional[date]:
    """从 DataFrame 中取最新日期（兼容 date/日期/trade_date 列名）。"""
    if df is None or df.empty:
        return None
    for col in ("date", "日期", "trade_date", "时间"):
        if col in df.columns:
            s = pd.to_datetime(df[col], errors="coerce").dropna()
            if not s.empty:
                return s.max().date()
    return None


def is_fresh(df: Optional[pd.DataFrame], max_lag_days: int,
             today: Optional[date] = None) -> Tuple[bool, str]:
    """判断数据是否新鲜：最新日期距今 ≤ max_lag_days。返回 (是否新鲜, 原因)。"""
    if df is None or df.empty:
        return False, "空数据"
    last = _last_date(df)
    if last is None:
        return False, "无日期列"
    today = today or date.today()
    lag = (today - last).days
    if lag > max_lag_days:
        return False, f"最新 {last.isoformat()}（滞后 {lag} 天 > {max_lag_days}）"
    return True, f"最新 {last.isoformat()}"


def _run_fetcher(name: str, args: Dict[str, Any],
                 fetchers: Dict[str, Callable[..., Optional[pd.DataFrame]]]):
    fn = fetchers.get(name)
    if fn is None:
        return None, "未知抓取器", 0
    t0 = time.time()
    try:
        df = fn(**args)
    except Exception as e:  # noqa: BLE001
        return None, f"异常: {repr(e)[:180]}", int((time.time() - t0) * 1000)
    return df, "", int((time.time() - t0) * 1000)


def _write_status(status_path: Path, dataset: str, payload: Dict[str, Any]) -> None:
    try:
        existing: Dict[str, Any] = {}
        if status_path.exists():
            existing = json.loads(status_path.read_text(encoding="utf-8"))
        datasets = existing.get("datasets", {})
        datasets[dataset] = payload
        existing["datasets"] = datasets
        existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(status_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("写 source_status.json 失败: %s", e)


def resolve_dataset(dataset: str, *, cfg: Optional[Dict[str, Any]] = None,
                    today: Optional[date] = None,
                    fetchers: Optional[Dict[str, Callable]] = None,
                    status_path: Optional[Path] = None,
                    write_status: bool = True) -> Optional[pd.DataFrame]:
    """按源链顺序取数，返回第一个「新鲜」的 DataFrame；全失败返回 None。

    Args:
        dataset: 数据集键（如 brent_oil）。
        cfg/fetchers/status_path: 便于测试注入。
    """
    cfg = cfg or load_source_config()
    fetchers = fetchers or FETCHERS
    status_path = status_path or STATUS_PATH
    entry = (cfg.get("datasets") or {}).get(dataset)
    if not entry:
        logger.warning("源链未配置数据集: %s", dataset)
        return None

    label = entry.get("label", dataset)
    default_lag = (cfg.get("defaults") or {}).get("max_lag_days", 6)
    max_lag = int(entry.get("max_lag_days", default_lag))

    attempts: List[Dict[str, Any]] = []
    chosen: Optional[str] = None
    result: Optional[pd.DataFrame] = None
    last_date_str = ""

    for src in entry.get("sources", []):
        name = src.get("name")
        args = src.get("args", {}) or {}
        df, err, ms = _run_fetcher(name, args, fetchers)
        ok, reason = is_fresh(df, max_lag, today)
        attempts.append({"source": name, "ok": ok, "reason": err or reason, "elapsed_ms": ms})
        if ok:
            chosen, result = name, df
            last_date_str = _last_date(df).isoformat() if _last_date(df) else ""
            logger.info("  %s: 命中源 '%s'（%s）", label, name, reason)
            break
        logger.warning("  %s: 源 '%s' 不可用（%s）", label, name, err or reason)

    if result is None:
        logger.warning("  %s: 所有源均失败，保留旧数据", label)

    if write_status:
        _write_status(status_path, dataset, {
            "label": label,
            "max_lag_days": max_lag,
            "ok": result is not None,
            "chosen": chosen,
            "last_date": last_date_str,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "sources": attempts,
        })
    return result


def probe_all(*, cfg: Optional[Dict[str, Any]] = None, today: Optional[date] = None,
              fetchers: Optional[Dict[str, Callable]] = None,
              status_path: Optional[Path] = None) -> Dict[str, Any]:
    """无条件探测链上每一个源（不做 failover），记录可达性与新鲜度。

    返回 {dataset: payload}，并写入 status 文件。
    """
    cfg = cfg or load_source_config()
    fetchers = fetchers or FETCHERS
    status_path = status_path or STATUS_PATH
    out: Dict[str, Any] = {}
    for dataset, entry in (cfg.get("datasets") or {}).items():
        label = entry.get("label", dataset)
        default_lag = (cfg.get("defaults") or {}).get("max_lag_days", 6)
        max_lag = int(entry.get("max_lag_days", default_lag))
        attempts = []
        chosen = None
        last_str = ""
        for src in entry.get("sources", []):
            name, args = src.get("name"), (src.get("args") or {})
            df, err, ms = _run_fetcher(name, args, fetchers)
            ok, reason = is_fresh(df, max_lag, today)
            ld = _last_date(df)
            attempts.append({"source": name, "ok": ok, "reason": err or reason,
                             "last_date": ld.isoformat() if ld else "", "elapsed_ms": ms})
            if ok and chosen is None:
                chosen = name
                last_str = ld.isoformat() if ld else ""
        payload = {"label": label, "max_lag_days": max_lag, "ok": chosen is not None,
                   "chosen": chosen, "last_date": last_str,
                   "updated_at": datetime.now().isoformat(timespec="seconds"),
                   "sources": attempts}
        _write_status(status_path, dataset, payload)
        out[dataset] = payload
    return out


def read_status(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取最近一次记录的状态；不存在返回 {}。"""
    path = path or STATUS_PATH
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 source_status.json 失败: %s", e)
    return {}
