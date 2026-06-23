"""Scheduled data refresh jobs for quant_factors."""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Callable, Optional

import akshare as ak
import pandas as pd

from core.refresh_manifest import RefreshManifest
from core.settings import REFRESH_MANIFEST_PATH

logger = logging.getLogger(__name__)


def fetch_fred_csv(series_id: str, name: str, start_date: str = "2020-01-01") -> Optional[pd.DataFrame]:
    """从 FRED 直接下载 CSV 数据。"""
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
        df = pd.read_csv(url)
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
            ("美元人民币", lambda: fetch_fred_csv("DEXCHUS", "USD/CNY汇率"), "usd_cny"),
            ("中国PMI", lambda: ak.macro_china_pmi(), "pmi"),
            ("中国CPI", lambda: ak.macro_china_cpi(), "cpi"),
            ("中国M2", lambda: ak.macro_china_money_supply(), "m2"),
            ("社融规模", lambda: first_valid_frame(fetch_pboc_social_financing, ak.macro_china_shrzgm), "social_financing"),
        ]

        failed = 0
        manifest = RefreshManifest(REFRESH_MANIFEST_PATH, "daily_domestic")
        for name, fetcher, filename in tasks:
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


def daily_data_refresh_foreign(data_bus):
    """定时任务：外盘数据刷新（次日06:00执行，确保外盘已收盘）。"""
    logger.info("开始外盘数据刷新...")
    try:
        from download_history import save_parquet, fetch_eia_crude_stock, fetch_brent_oil

        tasks = [
            ("天然气期货", lambda: ak.futures_foreign_hist(symbol="NG"), "natural_gas_futures"),
            ("CBOT大豆", fetch_cbot_soybean, "cbot_soybean"),
            ("VIX恐慌指数", lambda: ak.index_option_300etf_qvix(), "vix"),
            ("美国CPI", lambda: fetch_fred_csv("CPIAUCSL", "美国CPI"), "us_cpi"),
            ("布伦特原油", lambda: first_valid_frame(fetch_brent_oil, ak.energy_oil_hist), "brent_oil"),
            ("EIA原油库存", lambda: first_valid_frame(fetch_eia_crude_stock, ak.macro_usa_eia_crude_rate), "eia_crude_stock"),
            ("TIPS收益率", lambda: fetch_fred_csv("DFII10", "TIPS收益率"), "tips_yield"),
        ]

        failed = 0
        manifest = RefreshManifest(REFRESH_MANIFEST_PATH, "daily_foreign")
        for name, fetcher, filename in tasks:
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

        if failed == len(tasks):
            logger.error("所有外盘数据源刷新失败！请检查网络连接")
        elif failed > 0:
            logger.warning("外盘数据刷新部分失败: %d/%d", failed, len(tasks))

        data_bus.invalidate()
        manifest.write()
        logger.info("外盘数据刷新完成")
    except Exception as e:
        logger.error("外盘数据刷新异常: %s", e)
