"""Scheduled data refresh jobs for quant_factors."""
from __future__ import annotations

import logging
import time
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


def daily_data_refresh(data_bus):
    """定时任务：每日数据刷新（国内品种，18:00执行）。"""
    logger.info("开始每日数据刷新（国内品种）...")
    try:
        from download_history import save_parquet, fetch_tushare_futures, fetch_pboc_social_financing

        tasks = [
            ("生猪期货", lambda: fetch_tushare_futures("LH.DCE", "生猪期货"), "pork_futures"),
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
            ("动力煤期货", lambda: fetch_tushare_futures("ZC.ZCE", "动力煤期货"), "thermal_coal_futures"),
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

        data_bus.invalidate()
        manifest.write()
        logger.info("每日数据刷新（国内品种）完成")
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
