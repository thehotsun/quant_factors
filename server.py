import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
from waitress import serve
import pandas as pd
from datetime import datetime
from pathlib import Path
import yaml
import os
import logging
import akshare as ak

from core.factor_registry import FactorRegistry
from core.signal_aggregator import SignalAggregator
from core.data_bus import DataBus
from core.signal_logger import SignalLogger
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
            fv = _extract_factor_value(data)
            if fv is not None:
                _ic_monitor.snapshot(chain_name, fv, strength)
        except Exception as e:
            logger.warning(f"因子 {chain_name} IC快照失败: {e}")

    return {
        "factor_data": data,
        "opportunity": signal,
        "signal_strength": strength,
    }


def _extract_factor_value(data):
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
    for key in ["zscore", "ratio", "score", "value", "change", "spread", "margin", "diff"]:
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (ValueError, TypeError):
                continue
    for key in ["current_price", "current", "latest", "cpi_actual"]:
        if key in data and data[key] is not None:
            try:
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
            except Exception as e:
                results[chain_name_item] = {"error": str(e), "error_type": type(e).__name__}

    aggregated = SignalAggregator.aggregate(signals, method="weighted") if signals else None

    return jsonify({
        "chain": chain_name,
        "description": description,
        "active_signals": signals,
        "signal_count": len(signals),
        "aggregated_signal": aggregated,
        "all_results": results,
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
    """定时任务：每日数据刷新"""
    logger.info("开始每日数据刷新...")
    try:
        from download_history import save_parquet

        tasks = [
            ("生猪期货", lambda: ak.futures_main_sina(symbol="LH"), "pork_futures"),
            ("生猪远月", lambda: ak.futures_zh_daily_sina(symbol="LH2701"), "pork_futures_far"),
            ("鸡蛋期货", lambda: ak.futures_main_sina(symbol="JD"), "egg_futures"),
            ("豆粕期货", lambda: ak.futures_main_sina(symbol="M"), "soybean_meal_futures"),
            ("玉米期货", lambda: ak.futures_main_sina(symbol="C"), "corn_futures"),
            ("国产大豆", lambda: ak.futures_main_sina(symbol="A"), "soybean_domestic_futures"),
            ("进口大豆", lambda: ak.futures_main_sina(symbol="B"), "soybean_import_futures"),
            ("菜粕期货", lambda: ak.futures_main_sina(symbol="RM"), "rapeseed_meal_futures"),
            ("豆油期货", lambda: ak.futures_main_sina(symbol="Y"), "soybean_oil_futures"),
            ("原油期货", lambda: ak.futures_main_sina(symbol="SC"), "crude_oil_futures"),
            ("天然气期货", lambda: ak.futures_foreign_hist(symbol="NG"), "natural_gas_futures"),
            ("动力煤期货", lambda: ak.futures_main_sina(symbol="ZC"), "thermal_coal_futures"),
            ("铜期货", lambda: ak.futures_main_sina(symbol="CU"), "copper_futures"),
            ("铝期货", lambda: ak.futures_main_sina(symbol="AL"), "aluminum_futures"),
            ("螺纹钢", lambda: ak.futures_main_sina(symbol="RB"), "rebar_futures"),
            ("黄金期货", lambda: ak.futures_main_sina(symbol="AU"), "gold_futures"),
            ("白银期货", lambda: ak.futures_main_sina(symbol="AG"), "silver_futures"),
            ("美元人民币", lambda: ak.currency_boc_sina(symbol="美元"), "usd_cny"),
            ("中国PMI", lambda: ak.macro_china_pmi(), "pmi"),
            ("中国CPI", lambda: ak.macro_china_cpi(), "cpi"),
            ("中国M2", lambda: ak.macro_china_money_supply(), "m2"),
            ("CBOT大豆", lambda: ak.futures_foreign_hist(symbol="ZS"), "cbot_soybean"),
            ("铁矿石期货", lambda: ak.futures_main_sina(symbol="I"), "iron_ore_futures"),
            ("社融规模", lambda: ak.macro_china_shrzgm(), "social_financing"),
            ("VIX恐慌指数", lambda: ak.index_vix(), "vix"),
            ("美国CPI", lambda: ak.macro_usa_cpi(), "us_cpi"),
            ("布伦特原油", lambda: ak.energy_oil_hist(), "brent_oil"),
            ("EIA原油库存", lambda: ak.energy_eia_crude(), "eia_crude_stock"),
            ("TIPS收益率", lambda: ak.macro_usa_tips_yield(), "tips_yield"),
            ("鸡肉现货", lambda: ak.futures_spot_price(symbol="白羽肉鸡"), "chicken_spot"),
        ]

        for name, fetcher, filename in tasks:
            try:
                df = _retry_fetch(name, fetcher)
                save_parquet(df, filename)
                logger.info(f"  {name} 刷新成功")
            except Exception as e:
                logger.warning(f"  {name} 刷新失败（已重试3次）: {e}")

        _data_bus.invalidate()
        logger.info("每日数据刷新完成")
    except Exception as e:
        logger.error(f"每日数据刷新异常: {e}")


def _daily_ic_compute():
    """定时任务：每日 IC 计算"""
    logger.info("开始每日 IC 计算...")
    _ensure_imported()
    computed = 0
    for chain_name, cfg in CHAINS_CONFIG.items():
        if cfg.get("category") == "composite":
            continue
        data_deps = cfg.get("data_deps", [])
        if not data_deps:
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


def _init_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.error("APScheduler 未安装，定时任务不可用。请执行: pip install apscheduler")
        raise SystemExit(1)

    scheduler = BackgroundScheduler()
    scheduler.add_job(_daily_data_refresh, 'cron', hour=18, minute=0, id='daily_refresh')
    scheduler.add_job(_daily_ic_compute, 'cron', hour=18, minute=30, id='daily_ic')
    scheduler.start()
    logger.info("APScheduler 已启动: 每日 18:00 数据刷新, 18:30 IC 计算")


if __name__ == '__main__':
    _init_scheduler()
    serve(app, host='0.0.0.0', port=5001)