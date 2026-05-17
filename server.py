import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify

import pandas as pd
from datetime import datetime
from pathlib import Path
import yaml
import os
import logging
import akshare as ak
import tushare as ts

# Tushare 配置
TUSHARE_TOKEN = "165fb826f4b6e41aeb37ef84b7f4c99df784cbfec771ee139dfae048"
ts.set_token(TUSHARE_TOKEN)
tushare_pro = ts.pro_api()


def fetch_fred_csv(series_id, name, start_date="2020-01-01"):
    """从 FRED 直接下载 CSV 数据"""
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
        df = pd.read_csv(url)
        df = df.rename(columns={'observation_date': 'date'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        return df
    except Exception as e:
        logger.warning(f"{name} FRED下载失败: {e}")
        return None

from core.factor_registry import FactorRegistry
from core.signal_aggregator import SignalAggregator
from core.data_bus import DataBus
from core.signal_logger import SignalLogger
from core.push import get_push_manager, init_push_channels, format_signal_report
from evaluation.ic_monitor import ICMonitor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
DATA_DIR = Path("./data")

try:
    with open(Path(__file__).parent / "config" / "chains.yaml", "r", encoding="utf-8") as f:
        CHAINS_CONFIG = yaml.safe_load(f)["chains"]
except Exception as e:
    logger.error(f"加载 chains.yaml 失败: {e}")
    raise SystemExit(f"无法加载 chains.yaml: {e}")

_imported = False
_data_bus = DataBus(str(DATA_DIR))
_signal_logger = SignalLogger(str(DATA_DIR / "signals.db"))
_ic_monitor = ICMonitor(str(DATA_DIR / "ic_monitor.db"))


def _ensure_imported():
    global _imported
    if _imported:
        return
    import factors.meat.pork
    import factors.feed.soybean_meal
    import factors.feed.corn
    import factors.feed.soybean
    import factors.feed.rapeseed_meal
    import factors.cross.pig_grain_ratio
    import factors.cross.feed_cost
    import factors.cross.crush_margin
    import factors.cross.pig_chicken_spread
    import factors.cross.egg_feed_ratio
    import factors.cross.copper_gold_ratio
    import factors.cross.oil_gold_link
    import factors.cross.forex_commodity
    import factors.cross.pmi_metals
    import factors.macro.cpi
    import factors.macro.cpi_gold
    import factors.macro.pmi
    import factors.macro.forex
    import factors.macro.money_supply
    import factors.macro.cbot
    import factors.macro.social_financing
    import factors.macro.vix
    import factors.energy.energy
    import factors.energy.oil_assets
    import factors.metals.metals
    import factors.metals.silver
    import factors.metals.iron_ore
    import factors.cross.iron_rebar_cost
    import factors.technical.momentum
    import factors.technical.volatility
    import factors.technical.term_structure
    import factors.technical.seasonality
    _imported = True


_FACTOR_PARAMS = {}
try:
    _params_path = Path(__file__).parent / "config" / "factor_params.yaml"
    if _params_path.exists():
        with open(_params_path, "r", encoding="utf-8") as f:
            _params_config = yaml.safe_load(f)
            _FACTOR_PARAMS = _params_config.get("factors", {})
except Exception as e:
    logger.warning(f"加载 factor_params.yaml 失败: {e}")


def _instantiate_factor(chain_name):
    cfg = CHAINS_CONFIG.get(chain_name)
    if not cfg:
        return None
    module_path = cfg.get("factor_module")
    class_name = cfg.get("factor_class")
    if not module_path or not class_name:
        return None
    try:
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        factor_cfg = _FACTOR_PARAMS.get(chain_name, {})
        kwargs = {
            "data_dir": str(DATA_DIR),
            "adaptive": factor_cfg.get("adaptive", True),
            "params": factor_cfg.get("params", {}),
        }
        for key in ("symbol", "far_symbol"):
            if key in cfg:
                kwargs[key] = cfg[key]
        return cls(**kwargs)
    except Exception as e:
        logger.warning(f"实例化因子 {chain_name} 失败: {e}")
        return None


def _run_factor_chain(chain_name):
    factor = _instantiate_factor(chain_name)
    if factor is None:
        return None
    try:
        data = factor.calculate()
    except Exception as e:
        logger.error(f"因子 {chain_name} calculate 失败: {e}")
        return {"factor_data": None, "opportunity": None, "signal_strength": None, "error": str(e), "error_type": type(e).__name__}
    factor._cached_data = data
    try:
        signal = factor.signal()
    except Exception as e:
        logger.error(f"因子 {chain_name} signal 失败: {e}")
        signal = None
    strength = None
    if hasattr(factor, 'signal_strength'):
        try:
            strength = factor.signal_strength()
        except Exception as e:
            logger.warning(f"因子 {chain_name} signal_strength 计算失败: {e}")

    _signal_logger.log(chain_name, signal, strength, data)

    if data is not None:
        try:
            fv = _extract_factor_value(data, chain_name)
            if fv is not None:
                _ic_monitor.snapshot(chain_name, fv, strength)
            else:
                logger.debug(f"因子 {chain_name} 无有效因子值，跳过 IC 快照")
        except Exception as e:
            logger.warning(f"因子 {chain_name} IC快照失败: {e}")

    return {
        "factor_data": data,
        "opportunity": signal,
        "signal_strength": strength,
    }


def _extract_factor_value(data, factor_name: str = "unknown"):
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if not isinstance(data, dict):
        return None
    if "factor_value" in data and data["factor_value"] is not None:
        try:
            return float(data["factor_value"])
        except (ValueError, TypeError):
            pass

    _FALLBACK_KEYS = [
        "zscore", "zscore_20d", "ratio", "pig_grain_ratio", "egg_feed_ratio",
        "pig_chicken_ratio", "copper_gold_ratio", "oil_gas_ratio", "iron_rebar_ratio",
        "score", "momentum_score", "value", "change", "spread", "margin", "crush_margin",
        "diff", "divergence",
        "current_price", "current", "current_cpi", "current_pmi", "latest",
        "cpi_actual", "cbot_soybean", "vix_current", "usd_cny",
        "domestic_soybean", "iron_ore_price", "feed_cost_index",
        "m2_yoy", "sf_growth", "pmi",
        "cost_per_jin", "vol_ratio", "seasonal_avg_return", "seasonal_win_rate",
    ]
    for key in _FALLBACK_KEYS:
        if key in data and data[key] is not None:
            try:
                logger.debug(
                    f"因子 {factor_name} 未使用 'factor_value' 字段，"
                    f"通过 fallback key '{key}' 提取因子值。"
                )
                return float(data[key])
            except (ValueError, TypeError):
                continue
    return None


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


@app.route('/analyze/<chain>', methods=['GET'])
def analyze_auto(chain):
    _ensure_imported()

    if chain in CHAINS_CONFIG:
        result = _run_factor_chain(chain)
        if result:
            return jsonify({
                "chain": chain,
                "description": CHAINS_CONFIG[chain].get("description", ""),
                "category": CHAINS_CONFIG[chain].get("category", ""),
                "opportunity": result["opportunity"],
                "factor_data": result["factor_data"],
                "signal_strength": result.get("signal_strength"),
                "timestamp": datetime.now().isoformat()
            })

    return jsonify({"error": f"unknown chain: {chain}"}), 400


def _run_composite_chain(chain_name):
    _ensure_imported()
    cfg = CHAINS_CONFIG.get(chain_name, {})
    sub_chains = cfg.get("sub_chains", [])
    description = cfg.get("description", "")
    results = {}
    signals = []

    with ThreadPoolExecutor(max_workers=min(8, len(sub_chains))) as executor:
        future_map = {executor.submit(_run_factor_chain, name): name for name in sub_chains}
        for future in as_completed(future_map):
            chain_name_item = future_map[future]
            try:
                result = future.result()
                if result:
                    results[chain_name_item] = {
                        "description": CHAINS_CONFIG.get(chain_name_item, {}).get("description", ""),
                        "factor_data": result["factor_data"],
                        "opportunity": result["opportunity"],
                        "signal_strength": result.get("signal_strength"),
                    }
                    if result.get("error"):
                        results[chain_name_item]["error"] = result["error"]
                        results[chain_name_item]["error_type"] = result.get("error_type")
                    if result["opportunity"]:
                        sig = dict(result["opportunity"])
                        sig["_chain"] = chain_name_item
                        signals.append(sig)
                else:
                    logger.warning(f"综合链子链条 {chain_name_item} 返回None（因子实例化失败或chains.yaml配置错误）")
                    results[chain_name_item] = {"error": "因子实例化失败", "error_type": "InstantiationError"}
            except Exception as e:
                results[chain_name_item] = {"error": str(e), "error_type": type(e).__name__}

    aggregated = SignalAggregator.aggregate(signals, method="weighted") if signals else None

    all_failed = len(results) > 0 and all(r.get("error") for r in results.values())

    return jsonify({
        "chain": chain_name,
        "description": description,
        "active_signals": signals,
        "signal_count": len(signals),
        "aggregated_signal": aggregated,
        "all_results": results,
        "all_sub_chains_failed": all_failed,
        "error": "所有子链条均计算失败" if all_failed else None,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/analyze/full_meat_chain', methods=['GET'])
def full_meat_chain():
    return _run_composite_chain("full_meat_chain")


@app.route('/analyze/energy', methods=['GET'])
def energy_chain():
    return _run_composite_chain("energy_chain")


@app.route('/analyze/metals', methods=['GET'])
def metals_chain():
    return _run_composite_chain("metals_chain")


@app.route('/analyze/macro', methods=['GET'])
def macro_chain():
    return _run_composite_chain("macro_chain")


@app.route('/chains', methods=['GET'])
def list_chains():
    _ensure_imported()
    chain_list = []
    for name, cfg in CHAINS_CONFIG.items():
        chain_list.append({
            "name": name,
            "category": cfg.get("category", ""),
            "description": cfg.get("description", ""),
            "asset": cfg.get("asset", ""),
            "data_deps": cfg.get("data_deps", []),
        })
    return jsonify({"chains": chain_list, "total": len(chain_list)})


@app.route('/factor/<chain_name>', methods=['GET'])
def factor_data(chain_name):
    _ensure_imported()
    factor = _instantiate_factor(chain_name)
    if factor is None:
        return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
    try:
        data = factor.calculate()
        strength = None
        if hasattr(factor, 'signal_strength'):
            try:
                strength = factor.signal_strength()
            except Exception:
                pass
        return jsonify({
            "chain": chain_name,
            "factor_data": data,
            "signal_strength": strength,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e), "error_type": type(e).__name__}), 500


@app.route('/registry', methods=['GET'])
def list_registry():
    _ensure_imported()
    factors = FactorRegistry.list_all()
    return jsonify({
        "factors": factors,
        "total": len(factors),
    })


@app.route('/signal/<chain_name>', methods=['GET'])
def signal_only(chain_name):
    _ensure_imported()
    factor = _instantiate_factor(chain_name)
    if factor is None:
        return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
    try:
        signal = factor.signal()
        strength = None
        if hasattr(factor, 'signal_strength'):
            try:
                strength = factor.signal_strength()
            except Exception:
                pass
        _signal_logger.log(chain_name, signal, strength, None)
        return jsonify({
            "chain": chain_name,
            "signal": signal,
            "signal_strength": strength,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e), "error_type": type(e).__name__}), 500


@app.route('/signals/history', methods=['GET'])
def signal_history():
    factor_name = request.args.get('factor')
    days = int(request.args.get('days', 30))
    limit = int(request.args.get('limit', 100))
    rows = _signal_logger.query(factor_name=factor_name, days=days, limit=limit)
    return jsonify({
        "signals": rows,
        "count": len(rows),
        "query": {"factor": factor_name, "days": days, "limit": limit}
    })


@app.route('/signals/stats', methods=['GET'])
def signal_stats():
    factor_name = request.args.get('factor')
    days = int(request.args.get('days', 90))
    stats = _signal_logger.stats(factor_name=factor_name, days=days)
    return jsonify(stats)


@app.route('/ic/<factor_name>', methods=['GET'])
def ic_analysis(factor_name):
    _ensure_imported()
    cfg = CHAINS_CONFIG.get(factor_name)
    if not cfg:
        return jsonify({"error": f"unknown factor: {factor_name}"}), 400

    data_deps = cfg.get("data_deps", [])
    price_df = None
    for dep in data_deps:
        df = _data_bus.get(dep)
        if df is not None and len(df) > 20:
            price_df = df
            break

    if price_df is None:
        return jsonify({
            "factor_name": factor_name,
            "error": "no price data available for IC computation",
            "note": "需要该因子至少有 20 天以上的快照数据"
        })

    forward_days = int(request.args.get('forward_days', 5))
    window = int(request.args.get('window', 60))

    result = _ic_monitor.compute_ic(factor_name, price_df, forward_days=forward_days, window=window)
    if result is None:
        return jsonify({
            "factor_name": factor_name,
            "error": "insufficient snapshot data",
            "note": "因子快照数据不足，需要积累更多天的数据"
        })

    decay = _ic_monitor.get_decay_status(factor_name)
    result["decay"] = decay

    history = _ic_monitor.get_ic_history(factor_name, days=90)
    result["ic_history"] = history

    return jsonify(result)


@app.route('/ic/health', methods=['GET'])
def ic_health_report():
    _ensure_imported()
    report = _ic_monitor.health_report()

    decayed = [r for r in report if r.get("trend") in ("severe_decay", "moderate_decay")]
    warning = [r for r in report if r.get("trend") == "mild_decay"]
    healthy = [r for r in report if r.get("trend") == "stable"]

    return jsonify({
        "report": report,
        "summary": {
            "total": len(report),
            "healthy": len(healthy),
            "warning": len(warning),
            "decayed": len(decayed),
        },
        "decayed_factors": [r["factor_name"] for r in decayed],
        "timestamp": datetime.now().isoformat()
    })


def _retry_fetch(name, fetcher, max_retries=3, base_delay=2):
    for attempt in range(max_retries):
        try:
            return fetcher()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"  {name} 第{attempt+1}次失败: {e}，{delay}s后重试...")
                time.sleep(delay)
            else:
                raise


def _daily_data_refresh():
    """定时任务：每日数据刷新（国内品种，18:00执行）"""
    logger.info("开始每日数据刷新（国内品种）...")
    try:
        from download_history import save_parquet, fetch_tushare_futures

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
            ("社融规模", lambda: ak.macro_china_shrzgm(), "social_financing"),
        ]

        failed = 0
        for name, fetcher, filename in tasks:
            try:
                df = _retry_fetch(name, fetcher)
                save_parquet(df, filename)
                logger.info(f"  {name} 刷新成功")
            except Exception as e:
                failed += 1
                logger.warning(f"  {name} 刷新失败（已重试3次）: {e}")

        if failed == len(tasks):
            logger.error("所有国内数据源刷新失败！请检查网络连接")
        elif failed > 0:
            logger.warning(f"国内数据刷新部分失败: {failed}/{len(tasks)}")

        _data_bus.invalidate()
        logger.info("每日数据刷新（国内品种）完成")
    except Exception as e:
        logger.error(f"每日数据刷新异常: {e}")


def _daily_data_refresh_foreign():
    """定时任务：外盘数据刷新（次日06:00执行，确保外盘已收盘）"""
    logger.info("开始外盘数据刷新...")
    try:
        from download_history import save_parquet

        tasks = [
            ("天然气期货", lambda: ak.futures_foreign_hist(symbol="NG"), "natural_gas_futures"),
            ("VIX恐慌指数", lambda: ak.index_option_300etf_qvix(), "vix"),
            ("美国CPI", lambda: fetch_fred_csv("CPIAUCSL", "美国CPI"), "us_cpi"),
            ("布伦特原油", lambda: ak.energy_oil_hist(), "brent_oil"),
            ("EIA原油库存", lambda: ak.macro_usa_eia_crude_rate(), "eia_crude_stock"),
            ("TIPS收益率", lambda: fetch_fred_csv("DFII10", "TIPS收益率"), "tips_yield"),
        ]

        failed = 0
        for name, fetcher, filename in tasks:
            try:
                df = _retry_fetch(name, fetcher)
                save_parquet(df, filename)
                logger.info(f"  {name} 刷新成功")
            except Exception as e:
                failed += 1
                logger.warning(f"  {name} 刷新失败（已重试3次）: {e}")

        if failed == len(tasks):
            logger.error("所有外盘数据源刷新失败！请检查网络连接")
        elif failed > 0:
            logger.warning(f"外盘数据刷新部分失败: {failed}/{len(tasks)}")

        _data_bus.invalidate()
        logger.info("外盘数据刷新完成")
    except Exception as e:
        logger.error(f"外盘数据刷新异常: {e}")


def _daily_ic_compute():
    """定时任务：每日 IC 计算"""
    logger.info("开始每日 IC 计算...")
    _ensure_imported()

    _MONTHLY_SOURCES = {"cpi", "pmi", "m2", "social_financing", "us_cpi"}

    computed = 0
    for chain_name, cfg in CHAINS_CONFIG.items():
        if cfg.get("category") == "composite":
            continue
        data_deps = cfg.get("data_deps", [])
        if not data_deps:
            continue
        if data_deps[0] in _MONTHLY_SOURCES:
            continue
        price_df = _data_bus.get(data_deps[0])
        if price_df is None or len(price_df) < 20:
            continue
        try:
            result = _ic_monitor.compute_ic(chain_name, price_df)
            if result:
                computed += 1
        except Exception as e:
            logger.warning(f"  {chain_name} IC 计算失败: {e}")
    logger.info(f"每日 IC 计算完成，共计算 {computed} 个因子")


def _daily_push():
    """定时任务：每日推送分析结论（18:35执行，在数据刷新和IC计算之后）"""
    logger.info("开始每日分析推送...")
    composite_chains = [
        name for name, cfg in CHAINS_CONFIG.items()
        if cfg.get("category") == "composite"
    ]

    if not composite_chains:
        logger.warning("未配置综合链条，跳过推送")
        return

    push_mgr = get_push_manager()
    success_count = 0
    for chain_name in composite_chains:
        try:
            result = _run_composite_chain(chain_name)
            if hasattr(result, 'get_json'):
                result_data = result.get_json()
            else:
                import json as _json
                result_data = _json.loads(result.get_data(as_text=True))
            content = format_signal_report(result_data)
            title = f"量化分析日报 - {chain_name}"
            push_result = push_mgr.send(title, content)
            if any(push_result.values()):
                success_count += 1
        except Exception as e:
            logger.error(f"推送 {chain_name} 失败: {e}")

    logger.info(f"每日推送完成: {success_count}/{len(composite_chains)} 个链条推送成功")


def _init_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.error("APScheduler 未安装，定时任务不可用。请执行: pip install apscheduler")
        raise SystemExit(1)

    scheduler = BackgroundScheduler()
    scheduler.add_job(_daily_data_refresh, 'cron', hour=18, minute=0, id='daily_refresh')
    scheduler.add_job(_daily_data_refresh_foreign, 'cron', hour=6, minute=0, id='daily_refresh_foreign')
    scheduler.add_job(_daily_ic_compute, 'cron', hour=18, minute=30, id='daily_ic')
    scheduler.add_job(_daily_push, 'cron', hour=18, minute=35, id='daily_push')
    scheduler.start()
    logger.info("APScheduler 已启动: 每日 18:00 国内数据刷新, 次日 06:00 外盘数据刷新, 18:30 IC 计算, 18:35 推送")


@app.route('/push/<chain_name>', methods=['GET'])
def push_chain(chain_name):
    _ensure_imported()
    if chain_name not in CHAINS_CONFIG:
        return jsonify({"error": f"unknown chain: {chain_name}"}), 400

    cfg = CHAINS_CONFIG[chain_name]
    if cfg.get("category") == "composite":
        result = _run_composite_chain(chain_name)
    else:
        factor_result = _run_factor_chain(chain_name)
        result = jsonify({
            "chain": chain_name,
            "description": cfg.get("description", ""),
            "active_signals": [factor_result["opportunity"]] if factor_result and factor_result.get("opportunity") else [],
            "signal_count": 1 if factor_result and factor_result.get("opportunity") else 0,
            "aggregated_signal": factor_result.get("opportunity") if factor_result else None,
            "all_results": {chain_name: factor_result} if factor_result else {},
            "timestamp": datetime.now().isoformat()
        })

    if hasattr(result, 'get_json'):
        result_data = result.get_json()
    else:
        import json as _json
        result_data = _json.loads(result.get_data(as_text=True))

    content = format_signal_report(result_data)
    title = f"量化分析 - {chain_name}"
    push_mgr = get_push_manager()
    push_result = push_mgr.send(title, content)

    return jsonify({
        "chain": chain_name,
        "push_result": push_result,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })


# 初始化（gunicorn import 时自动执行）
init_push_channels()
_init_scheduler()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)