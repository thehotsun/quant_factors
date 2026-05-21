from flask import Flask, request, jsonify

from datetime import datetime
from pathlib import Path
import yaml
import logging
from core.factor_runner import FactorRunner
from core.data_refresh import daily_data_refresh, daily_data_refresh_foreign
from core.scheduler import init_scheduler
from core.composite_runner import run_composite_chain

from core.factor_registry import FactorRegistry
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

_data_bus = DataBus(str(DATA_DIR))
_signal_logger = SignalLogger(str(DATA_DIR / "signals.db"))
_ic_monitor = ICMonitor(str(DATA_DIR / "ic_monitor.db"))
_FACTOR_PARAMS = {}
try:
    _params_path = Path(__file__).parent / "config" / "factor_params.yaml"
    if _params_path.exists():
        with open(_params_path, "r", encoding="utf-8") as f:
            _params_config = yaml.safe_load(f)
            _FACTOR_PARAMS = _params_config.get("factors", {})
except Exception as e:
    logger.warning(f"加载 factor_params.yaml 失败: {e}")


_runner = FactorRunner(CHAINS_CONFIG, _FACTOR_PARAMS, DATA_DIR, _signal_logger, _ic_monitor)


def _instantiate_factor(chain_name):
    return _runner.instantiate(chain_name)


def _run_factor_chain(chain_name):
    return _runner.run_chain(chain_name)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


@app.route('/analyze/<chain>', methods=['GET'])
def analyze_auto(chain):
    _runner.ensure_imported()

    cfg = CHAINS_CONFIG.get(chain)
    if cfg:
        if cfg.get("category") == "composite":
            return _run_composite_chain(chain)

        result = _run_factor_chain(chain)
        if result:
            return jsonify({
                "chain": chain,
                "description": cfg.get("description", ""),
                "category": cfg.get("category", ""),
                "opportunity": result["opportunity"],
                "factor_data": result["factor_data"],
                "signal_strength": result.get("signal_strength"),
                "timestamp": datetime.now().isoformat()
            })

    return jsonify({"error": f"unknown chain: {chain}"}), 400


def _run_composite_chain(chain_name):
    return jsonify(run_composite_chain(
        chain_name,
        CHAINS_CONFIG,
        _run_factor_chain,
        ensure_imported=_runner.ensure_imported,
    ))


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
    _runner.ensure_imported()
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
    _runner.ensure_imported()
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
    _runner.ensure_imported()
    factors = FactorRegistry.list_all()
    return jsonify({
        "factors": factors,
        "total": len(factors),
    })


@app.route('/signal/<chain_name>', methods=['GET'])
def signal_only(chain_name):
    _runner.ensure_imported()
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
    _runner.ensure_imported()
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
    _runner.ensure_imported()
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



def _daily_data_refresh():
    return daily_data_refresh(_data_bus)


def _daily_data_refresh_foreign():
    return daily_data_refresh_foreign(_data_bus)


def _daily_ic_compute():
    """定时任务：每日 IC 计算"""
    logger.info("开始每日 IC 计算...")
    _runner.ensure_imported()

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
    with app.app_context():
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
                content = format_signal_report(result_data, _data_bus)
                title = f"量化分析日报 - {chain_name}"
                push_result = push_mgr.send(title, content)
                if any(push_result.values()):
                    success_count += 1
            except Exception as e:
                logger.error(f"推送 {chain_name} 失败: {e}")

        logger.info(f"每日推送完成: {success_count}/{len(composite_chains)} 个链条推送成功")



def _init_scheduler():
    return init_scheduler(
        _daily_data_refresh,
        _daily_data_refresh_foreign,
        _daily_ic_compute,
        _daily_push,
    )


@app.route('/push/<chain_name>', methods=['GET'])
def push_chain(chain_name):
    _runner.ensure_imported()
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

    content = format_signal_report(result_data, _data_bus)
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