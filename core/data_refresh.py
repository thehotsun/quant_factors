"""Scheduled data refresh jobs for quant_factors."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Callable, Optional

import akshare as ak
import pandas as pd
import requests

from core.refresh_manifest import RefreshManifest
from core.settings import DATA_DIR, REFRESH_MANIFEST_PATH

logger = logging.getLogger(__name__)

# 出站请求超时（秒）。FRED 曾出现连接挂起导致整个刷新任务永久阻塞。
FRED_TIMEOUT = 30


def fetch_fred_csv(series_id: str, name: str, start_date: str = "2020-01-01") -> Optional[pd.DataFrame]:
    """从 FRED 直接下载 CSV 数据（带超时，避免连接挂起阻塞刷新任务）。"""
    try:
        url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
               f"?id={series_id}&cosd={start_date}")
        resp = requests.get(url, timeout=FRED_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        df = df.rename(columns={"observation_date": "date"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        return df
    except Exception as e:
        logger.warning("%s FRED下载失败: %s", name, e)
        return None


def fetch_cbot_soybean() -> Optional[pd.DataFrame]:
    """下载 CBOT 大豆连续合约历史数据。"""
    try:
        df = ak.futures_foreign_hist(symbol="S")
        if df is None or df.empty:
            logger.warning("CBOT大豆下载为空")
            return None
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume", "position", "settlement"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date")
        df.reset_index(drop=True, inplace=True)
        return df
    except Exception as e:
        logger.warning("CBOT大豆下载失败: %s", e)
        return None


def first_valid_frame(*fetchers: Callable[[], Optional[pd.DataFrame]]) -> Optional[pd.DataFrame]:
    """Return the first non-empty DataFrame from a sequence of fetchers."""
    for fetcher in fetchers:
        df = fetcher()
        if df is not None and not df.empty:
            return df
    return None


def retry_fetch(name: str, fetcher: Callable[[], pd.DataFrame], max_retries: int = 3,
                base_delay: int = 2):
    for attempt in range(max_retries):
        try:
            return fetcher()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("  %s 第%d次失败: %s，%ss后重试...", name, attempt + 1, e, delay)
                time.sleep(delay)
            else:
                raise


def _refresh_spot_data(manifest):
    """刷新现货数据（生意社 soozhu + 上海金交所）。"""
    from data_sources.spot import (
        fetch_pork_spot, fetch_gold_spot, fetch_silver_spot, fetch_platinum_spot,
        fetch_copper_spot, fetch_corn_spot, fetch_soybean_meal_spot,
        fetch_egg_spot, fetch_soybean_oil_spot, fetch_rapeseed_meal_spot,
        fetch_rebar_spot, fetch_iron_ore_spot, fetch_aluminum_spot,
        fetch_soybean_domestic_spot,
    )
    from download_history import save_parquet

    spot_tasks = [
        ("生猪现货", fetch_pork_spot, "pork_spot"),
        ("黄金现货", fetch_gold_spot, "gold_spot"),
        ("白银现货", fetch_silver_spot, "silver_spot"),
        ("铂金现货", fetch_platinum_spot, "platinum_spot"),
        ("铜现货", lambda: fetch_copper_spot(start_day="20240101"), "copper_spot"),
        ("玉米现货", lambda: fetch_corn_spot(start_day="20240101"), "corn_spot"),
        ("豆粕现货", lambda: fetch_soybean_meal_spot(start_day="20240101"), "soybean_meal_spot"),
        ("鸡蛋现货", lambda: fetch_egg_spot(start_day="20240101"), "egg_spot"),
        ("豆油现货", lambda: fetch_soybean_oil_spot(start_day="20240101"), "soybean_oil_spot"),
        ("菜粕现货", lambda: fetch_rapeseed_meal_spot(start_day="20240101"), "rapeseed_meal_spot"),
        ("螺纹钢现货", lambda: fetch_rebar_spot(start_day="20240101"), "rebar_spot"),
        ("铁矿石现货", lambda: fetch_iron_ore_spot(start_day="20240101"), "iron_ore_spot"),
        ("铝现货", lambda: fetch_aluminum_spot(start_day="20240101"), "aluminum_spot"),
        ("国产大豆现货", lambda: fetch_soybean_domestic_spot(start_day="20240101"), "soybean_domestic_spot"),
    ]

    for name, fetcher, filename in spot_tasks:
        try:
            df = retry_fetch(name, fetcher)
            wrote = save_parquet(df, filename)
            if wrote:
                manifest.record(name=name, filename=filename, status="success", df=df, wrote=True)
                logger.info("  %s 刷新成功", name)
            else:
                manifest.record(name=name, filename=filename, status="skipped", df=df, wrote=False)
                logger.warning("  %s 刷新跳过（无有效数据）", name)
        except Exception as e:
            manifest.record(name=name, filename=filename, status="failed", df=None, error=str(e), wrote=False)
            logger.warning("  %s 刷新失败: %s", name, e)


def _save_macro_pit_snapshots(data_bus):
    """Save point-in-time snapshots for macro data to avoid forward-looking bias.

    Called after daily data refresh. Saves current macro data with timestamp
    so backtests can use data that was actually available at that time.
    """
    from core.macro_calendar import save_pit_snapshot, invalidate_fetch_timestamp_cache
    from core.settings import DATA_DIR

    # Invalidate fetch timestamp cache so we pick up new manifest
    invalidate_fetch_timestamp_cache()

    macro_series = ["cpi", "pmi", "m2", "social_financing", "us_cpi"]
    saved = 0
    for series_name in macro_series:
        df = data_bus.get(series_name)
        if df is not None and len(df) > 0:
            path = save_pit_snapshot(df, series_name)
            if path:
                saved += 1
                logger.info("  PIT快照已保存: %s", series_name)

    if saved > 0:
        logger.info("宏观PIT快照保存完成: %d/%d", saved, len(macro_series))


def _save_spot_prev_close():
    """保存现货前收盘价，供盘中异动告警对比。

    优先从 soozhu 获取（与盘中实时监控同源），避免数据源口径不一致。
    无 soozhu 接口的品种从 parquet（生意社）获取。
    """
    import json
    from core.settings import DATA_DIR

    prev_close = {}
    data_dir = str(DATA_DIR)

    # ── 有 soozhu 接口的品种：从 soozhu 获取，保证与实时监控同源 ──
    _soozhu_fetchers = [
        # (key, akshare接口名, 单位换算因子, 展示名)
        ("pork",      "spot_hog_soozhu",            1000, "生猪"),
        ("corn",      "spot_corn_price_soozhu",     1000, "玉米"),
        # soybean_domestic 已移除：soozhu 与期货合约A品种不匹配
    ]

    try:
        import akshare as ak
    except ImportError:
        ak = None

    if ak is not None:
        for key, api_name, factor, label in _soozhu_fetchers:
            try:
                fn = getattr(ak, api_name, None)
                if fn is None:
                    continue
                df = fn()
                if df is None or df.empty or '价格' not in df.columns:
                    continue
                if '日期' in df.columns and len(df) >= 2:
                    # 有历史序列：过滤非交易日，取最近两个工作日
                    from core.market_alert import _pick_trading_day_pair
                    cur_row, prev_row = _pick_trading_day_pair(df)
                    if prev_row is not None:
                        prev_close[key] = {
                            "price": float(prev_row['价格']) * factor,
                            "date": str(prev_row['日期']),
                        }
                    elif cur_row is not None:
                        # 只找到一行，用当日价格
                        prev_close[key] = {
                            "price": float(cur_row['价格']) * factor,
                            "date": str(cur_row['日期']),
                        }
                else:
                    # 只有省份数据（如生猪）：取各省均价作为基准
                    prev_close[key] = {
                        "price": float(df['价格'].mean()) * factor,
                        "date": date.today().isoformat(),
                    }
                logger.info("soozhu 现货前收盘: %s = %.2f 元/吨", label, prev_close[key]["price"])
            except Exception as e:
                logger.warning("soozhu %s 现货前收盘获取失败，回退 parquet: %s", label, e)

    # ── 无 soozhu 接口的品种 + soozhu 获取失败的品种：从 parquet 获取 ──
    spot_files = {
        "pork": "pork_spot",
        "egg": "egg_spot",
        "soybean_meal": "soybean_meal_spot",
        "corn": "corn_spot",
        "soybean_oil": "soybean_oil_spot",
        "rapeseed_meal": "rapeseed_meal_spot",
        "copper": "copper_spot",
        "aluminum": "aluminum_spot",
        "rebar": "rebar_spot",
        "gold": "gold_spot",
        "silver": "silver_spot",
        "platinum": "platinum_spot",
        "iron_ore": "iron_ore_spot",
        "soybean_domestic": "soybean_domestic_spot",
    }

    for key, filename in spot_files.items():
        if key in prev_close:
            continue  # soozhu 已获取，跳过
        path = os.path.join(data_dir, f"{filename}.parquet")
        try:
            df = pd.read_parquet(path)
            if df is not None and not df.empty and 'close' in df.columns:
                last_row = df.dropna(subset=['close']).iloc[-1]
                prev_close[key] = {
                    "price": float(last_row['close']),
                    "date": str(last_row['date'].date()) if 'date' in df.columns else "",
                }
        except Exception:
            pass

    out_path = os.path.join(data_dir, "spot_prev_close.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(prev_close, f, ensure_ascii=False, indent=2)
        logger.info("现货前收盘价已保存: %d 个品种", len(prev_close))
    except Exception as e:
        logger.warning("保存现货前收盘价失败: %s", e)


def daily_data_refresh(data_bus):
    """定时任务：每日数据刷新（国内品种，18:00执行）。"""
    logger.info("开始每日数据刷新（国内品种）...")
    try:
        from download_history import save_parquet, fetch_tushare_futures, fetch_pboc_social_financing, fetch_pork_futures_far

        tasks = [
            ("生猪期货", lambda: fetch_tushare_futures("LH.DCE", "生猪期货"), "pork_futures"),
            ("生猪远月/主力期货代理", fetch_pork_futures_far, "pork_futures_far"),
            ("鸡蛋期货", lambda: fetch_tushare_futures("JD.DCE", "鸡蛋期货"), "egg_futures"),
            ("豆粕期货", lambda: fetch_tushare_futures("M.DCE", "豆粕期货"), "soybean_meal_futures"),
            ("玉米期货", lambda: fetch_tushare_futures("C.DCE", "玉米期货"), "corn_futures"),
            ("国产大豆", lambda: fetch_tushare_futures("A.DCE", "国产大豆"), "soybean_domestic_futures"),
            ("进口大豆", lambda: fetch_tushare_futures("B.DCE", "进口大豆"), "soybean_import_futures"),
            ("菜粕期货", lambda: fetch_tushare_futures("RM.ZCE", "菜粕期货"), "rapeseed_meal_futures"),
            ("豆油期货", lambda: fetch_tushare_futures("Y.DCE", "豆油期货"), "soybean_oil_futures"),
            ("原油期货", lambda: fetch_tushare_futures("SC.INE", "原油期货"), "crude_oil_futures"),
            ("铜期货", lambda: fetch_tushare_futures("CU.SHF", "铜期货"), "copper_futures"),
            ("铝期货", lambda: fetch_tushare_futures("AL.SHF", "铝期货"), "aluminum_futures"),
            ("螺纹钢", lambda: fetch_tushare_futures("RB.SHF", "螺纹钢"), "rebar_futures"),
            ("黄金期货", lambda: fetch_tushare_futures("AU.SHF", "黄金期货"), "gold_futures"),
            ("白银期货", lambda: fetch_tushare_futures("AG.SHF", "白银期货"), "silver_futures"),
            ("铂金期货", lambda: fetch_tushare_futures("PT.SHF", "铂金期货"), "platinum_futures"),
            # ("动力煤期货", lambda: fetch_tushare_futures("ZC.ZCE", "动力煤期货"), "thermal_coal_futures"),  # 已废弃：国家限价后失去市场化定价功能
            ("铁矿石期货", lambda: fetch_tushare_futures("I.DCE", "铁矿石期货"), "iron_ore_futures"),
            ("美元人民币", None, "usd_cny"),  # 源链容灾：FRED → 中行牌价（config/data_sources.yaml）
            ("中国PMI", lambda: ak.macro_china_pmi(), "pmi"),
            ("中国CPI", lambda: ak.macro_china_cpi(), "cpi"),
            ("中国M2", lambda: ak.macro_china_money_supply(), "m2"),
            ("社融规模", lambda: first_valid_frame(fetch_pboc_social_financing, ak.macro_china_shrzgm), "social_financing"),
        ]

        failed = 0
        manifest = RefreshManifest(REFRESH_MANIFEST_PATH, "daily_domestic")
        from core.source_chain import resolve_dataset as _resolve_dataset
        for name, fetcher, filename in tasks:
            df = None
            try:
                # fetcher 为 None 表示走源链容灾（config/data_sources.yaml）
                df = retry_fetch(name, fetcher) if fetcher is not None else _resolve_dataset(filename)
                wrote = save_parquet(df, filename)
                if wrote:
                    manifest.record(name=name, filename=filename, status="success", df=df, wrote=True)
                    logger.info("  %s 刷新成功", name)
                else:
                    manifest.record(name=name, filename=filename, status="skipped", df=df, wrote=False)
                    logger.warning("  %s 刷新跳过（无有效数据）", name)
            except Exception as e:
                failed += 1
                manifest.record(name=name, filename=filename, status="failed", df=df, error=str(e), wrote=False)
                logger.warning("  %s 刷新失败（已重试3次）: %s", name, e)

        if failed == len(tasks):
            logger.error("所有国内数据源刷新失败！请检查网络连接")
        elif failed > 0:
            logger.warning("国内数据刷新部分失败: %d/%d", failed, len(tasks))

        # ── 现货数据刷新 ─────────────────────────────────────────
        _refresh_spot_data(manifest)

        data_bus.invalidate()
        manifest.write()
        logger.info("每日数据刷新（国内品种）完成")

        # 保存宏观数据 PIT 快照（避免前视偏差）
        _save_macro_pit_snapshots(data_bus)

        # 保存现货前收盘价供盘中异动对比
        _save_spot_prev_close()
    except Exception as e:
        logger.error("每日数据刷新异常: %s", e)


# 走「源链」容灾的外盘数据集：{数据集键: 展示名}（见 config/data_sources.yaml）
_CHAINED_FOREIGN = {
    "natural_gas_futures": "天然气期货",
    "cbot_soybean": "CBOT大豆",
    "brent_oil": "布伦特原油",
    "eia_crude_stock": "EIA原油库存",
}


def daily_data_refresh_foreign(data_bus):
    """定时任务：外盘数据刷新（次日06:00执行，确保外盘已收盘）。"""
    logger.info("开始外盘数据刷新...")
    try:
        from download_history import save_parquet
        from core.source_chain import resolve_dataset

        failed = 0
        manifest = RefreshManifest(REFRESH_MANIFEST_PATH, "daily_foreign")

        # ① 源链数据集：按配置的源链逐个尝试，命中即用；全失败/陈旧 → 保留旧数据
        for dataset, label in _CHAINED_FOREIGN.items():
            df = None
            try:
                df = resolve_dataset(dataset)
                wrote = save_parquet(df, dataset)
                if wrote:
                    manifest.record(name=label, filename=dataset, status="success", df=df, wrote=True)
                    logger.info("  %s 刷新成功", label)
                else:
                    manifest.record(name=label, filename=dataset, status="skipped", df=df, wrote=False)
                    logger.warning("  %s 刷新跳过（所有源失败或数据陈旧，保留旧数据）", label)
            except Exception as e:
                failed += 1
                manifest.record(name=label, filename=dataset, status="failed", df=df, error=str(e), wrote=False)
                logger.warning("  %s 刷新失败: %s", label, e)

        # ② 其余单源数据集（无备用源，保留原有重试）
        single_tasks = [
            ("VIX恐慌指数", lambda: ak.index_option_300etf_qvix(), "vix"),
            ("美国CPI", lambda: fetch_fred_csv("CPIAUCSL", "美国CPI"), "us_cpi"),
            ("TIPS收益率", lambda: fetch_fred_csv("DFII10", "TIPS收益率"), "tips_yield"),
        ]
        for name, fetcher, filename in single_tasks:
            df = None
            try:
                df = retry_fetch(name, fetcher)
                wrote = save_parquet(df, filename)
                if wrote:
                    manifest.record(name=name, filename=filename, status="success", df=df, wrote=True)
                    logger.info("  %s 刷新成功", name)
                else:
                    manifest.record(name=name, filename=filename, status="skipped", df=df, wrote=False)
                    logger.warning("  %s 刷新跳过（无有效数据）", name)
            except Exception as e:
                failed += 1
                manifest.record(name=name, filename=filename, status="failed", df=df, error=str(e), wrote=False)
                logger.warning("  %s 刷新失败（已重试3次）: %s", name, e)

        total = len(_CHAINED_FOREIGN) + len(single_tasks)
        if failed == total:
            logger.error("所有外盘数据源刷新失败！请检查网络连接")
        elif failed > 0:
            logger.warning("外盘数据刷新部分失败: %d/%d", failed, total)

        data_bus.invalidate()
        manifest.write()
        logger.info("外盘数据刷新完成")
    except Exception as e:
        logger.error("外盘数据刷新异常: %s", e)


# ── 数据新鲜度监控 ──────────────────────────────────────────
# (文件名, 展示名, 允许滞后天数)。滞后超过阈值即视为数据停摆。
_FRESHNESS_SERIES = [
    ("pork_futures", "生猪期货", 4),
    ("egg_futures", "鸡蛋期货", 4),
    ("soybean_meal_futures", "豆粕期货", 4),
    ("corn_futures", "玉米期货", 4),
    ("rapeseed_meal_futures", "菜粕期货", 4),
    ("soybean_oil_futures", "豆油期货", 4),
    ("crude_oil_futures", "原油期货", 4),
    ("copper_futures", "铜期货", 4),
    ("aluminum_futures", "铝期货", 4),
    ("rebar_futures", "螺纹钢期货", 4),
    ("gold_futures", "黄金期货", 4),
    ("silver_futures", "白银期货", 4),
    ("iron_ore_futures", "铁矿石期货", 4),
    ("brent_oil", "布伦特原油", 6),
    ("usd_cny", "美元人民币", 6),
    ("natural_gas_futures", "天然气期货", 6),
    ("cbot_soybean", "CBOT大豆", 6),
    ("vix", "VIX恐慌指数", 6),
]


def check_data_freshness(push: bool = True, max_lag_days: Optional[int] = None):
    """检查关键数据的新鲜度，滞后过多时告警。

    用于发现“刷新任务静默停摆”：例如任务因网络挂起被跳过时，数据会一直
    停留在旧日期而不报错。返回问题列表（为空表示全部正常）。
    """
    today = date.today()
    problems = []

    for fname, label, tol in _FRESHNESS_SERIES:
        threshold = max_lag_days if max_lag_days is not None else tol
        path = Path(DATA_DIR) / f"{fname}.parquet"
        if not path.exists():
            problems.append(f"{label}: 数据文件缺失")
            continue
        try:
            df = pd.read_parquet(path)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{label}: 读取失败 {e}")
            continue
        if df is None or df.empty or "date" not in df.columns:
            problems.append(f"{label}: 无有效数据")
            continue
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if dates.empty:
            problems.append(f"{label}: 无有效日期")
            continue
        last = dates.max().date()
        lag = (today - last).days
        if lag > threshold:
            problems.append(f"{label}: 最新 {last}（滞后 {lag} 天）")

    # 刷新清单：上次成功结束距今过久，说明刷新任务停摆
    try:
        manifest_path = Path(REFRESH_MANIFEST_PATH)
        if manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            ended = payload.get("ended_at")
            if ended:
                lag_hours = (datetime.now() - datetime.fromisoformat(ended)).total_seconds() / 3600
                if lag_hours > 48:
                    problems.append(
                        f"刷新任务: 上次结束于 {ended}（{lag_hours:.0f} 小时前）")
    except Exception as e:  # noqa: BLE001
        logger.warning("刷新清单检查失败: %s", e)

    # 源链失败：所有源都不可用/不新鲜的数据集（已沿用旧数据）
    try:
        from core.source_chain import read_status
        for key, st in (read_status().get("datasets") or {}).items():
            if not st.get("ok", True):
                label = st.get("label", key)
                srcs = "、".join(s.get("source", "?") for s in st.get("sources", []))
                problems.append(f"{label}: 所有源均失败（{srcs}），沿用旧数据")
    except Exception as e:  # noqa: BLE001
        logger.warning("源链状态检查失败: %s", e)

    if problems:
        detail = "\n".join(f"- {p}" for p in problems)
        logger.warning("数据新鲜度告警: %d 项异常\n%s", len(problems), detail)
        if push:
            try:
                from core.push import get_push_manager
                get_push_manager().send(
                    "量化系统告警：数据过期",
                    "⚠️ **数据新鲜度告警**\n" + detail,
                )
            except Exception as e:  # noqa: BLE001
                logger.error("新鲜度告警推送失败: %s", e)
    else:
        logger.info("数据新鲜度检查通过（全部为最新）")
    return problems
