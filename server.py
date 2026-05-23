from flask import Flask, request, jsonify

from datetime import datetime
import logging
from core.factor_runner import FactorRunner
from core.data_refresh import daily_data_refresh, daily_data_refresh_foreign
from core.scheduler import init_scheduler
from core.composite_runner import run_composite_chain
from core.ic_service import compute_daily_ic
from core.push_service import send_chain_push, push_daily_composite_reports
from core.chain_config import build_chain_definitions, check_metadata_consistency
from evaluation.trigger_backtest import trigger_backtest, format_trigger_report

from core.factor_registry import FactorRegistry
from core.data_bus import DataBus
from core.signal_logger import SignalLogger
from core.push import init_push_channels
from core.settings import DATA_DIR, SIGNALS_DB_PATH, IC_DB_PATH, load_chains_config, load_factor_params
from evaluation.ic_monitor import ICMonitor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

try:
    CHAINS_CONFIG = load_chains_config()
    FactorRegistry.sync_from_chains(CHAINS_CONFIG)
except Exception as e:
    raise SystemExit(f"无法加载 chains.yaml: {e}")

# Unified immutable chain definitions (merges chains.yaml + registry metadata)
CHAIN_DEFS = build_chain_definitions(CHAINS_CONFIG, registry_info_fn=FactorRegistry.info)
_metadata_diffs = check_metadata_consistency(CHAINS_CONFIG, FactorRegistry.info)
if _metadata_diffs:
    for _d in _metadata_diffs:
        logger.warning("链条 %s 字段 %s 不一致: yaml=%r registry=%r", _d.chain, _d.field, _d.yaml_value, _d.registry_value)

_data_bus = DataBus(str(DATA_DIR))
_signal_logger = SignalLogger(str(SIGNALS_DB_PATH))
_ic_monitor = ICMonitor(str(IC_DB_PATH))
_FACTOR_PARAMS = load_factor_params()


_runner = FactorRunner(CHAINS_CONFIG, _FACTOR_PARAMS, DATA_DIR, _signal_logger, _ic_monitor, chain_defs=CHAIN_DEFS)


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

        result = _runner.run_chain(chain)
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
        _runner.run_chain,
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
    result = _runner.calculate_only(chain_name)
    if result is None:
        return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
    if result.get("error"):
        return jsonify({"error": result["error"], "error_type": result.get("error_type", "")}), 500
    return jsonify({
        "chain": chain_name,
        "factor_data": result["factor_data"],
        "signal_strength": result.get("signal_strength"),
        "timestamp": datetime.now().isoformat()
    })


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
    result = _runner.signal_only(chain_name)
    if result is None:
        return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
    if result.get("error"):
        return jsonify({"error": result["error"], "error_type": result.get("error_type", "")}), 500
    return jsonify({
        "chain": chain_name,
        "signal": result.get("signal"),
        "signal_strength": result.get("signal_strength"),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/signals/history', methods=['GET'])
def signal_history():
    factor_name = request.args.get('factor')
    days = int(request.args.get('days', 30))
    limit = int(request.args.get('limit', 100))
    as_of = request.args.get('as_of')
    run_id = request.args.get('run_id')
    trigger = request.args.get('trigger')
    direction = request.args.get('direction')
    rows = _signal_logger.query(
        factor_name=factor_name,
        days=days,
        limit=limit,
        as_of=as_of,
        run_id=run_id,
        trigger=trigger,
        direction=direction,
    )
    query = {
        "factor": factor_name,
        "days": days,
        "limit": limit,
        "as_of": as_of,
        "run_id": run_id,
        "trigger": trigger,
        "direction": direction,
    }
    return jsonify({
        "signals": rows,
        "count": len(rows),
        "query": query,
    })


@app.route('/signals/stats', methods=['GET'])
def signal_stats():
    factor_name = request.args.get('factor')
    days = int(request.args.get('days', 90))
    as_of = request.args.get('as_of')
    run_id = request.args.get('run_id')
    trigger = request.args.get('trigger')
    direction = request.args.get('direction')
    stats = _signal_logger.stats(
        factor_name=factor_name,
        days=days,
        as_of=as_of,
        run_id=run_id,
        trigger=trigger,
        direction=direction,
    )
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
    return compute_daily_ic(
        CHAINS_CONFIG,
        _data_bus,
        _ic_monitor,
        _runner.ensure_imported,
    )


def _daily_push():
    return push_daily_composite_reports(app, CHAINS_CONFIG, _run_composite_chain, _data_bus)



def _init_scheduler():
    return init_scheduler(
        _daily_data_refresh,
        _daily_data_refresh_foreign,
        _daily_ic_compute,
        _daily_push,
    )


@app.route('/trigger_backtest', methods=['GET'])
def trigger_backtest_endpoint():
    _runner.ensure_imported()
    days = int(request.args.get('days', 365))
    min_samples = int(request.args.get('min_samples', 3))
    report = trigger_backtest(CHAINS_CONFIG, _data_bus, _signal_logger, days=days, min_samples=min_samples)
    return jsonify(report)


@app.route('/push/<chain_name>', methods=['GET'])
def push_chain(chain_name):
    _runner.ensure_imported()
    if chain_name not in CHAINS_CONFIG:
        return jsonify({"error": f"unknown chain: {chain_name}"}), 400

    cfg = CHAINS_CONFIG[chain_name]
    if cfg.get("category") == "composite":
        result = _run_composite_chain(chain_name)
    else:
        factor_result = _runner.run_chain(chain_name)
        result = jsonify({
            "chain": chain_name,
            "description": cfg.get("description", ""),
            "active_signals": [factor_result["opportunity"]] if factor_result and factor_result.get("opportunity") else [],
            "signal_count": 1 if factor_result and factor_result.get("opportunity") else 0,
            "aggregated_signal": factor_result.get("opportunity") if factor_result else None,
            "all_results": {chain_name: factor_result} if factor_result else {},
            "timestamp": datetime.now().isoformat()
        })

    return jsonify(send_chain_push(chain_name, cfg, result, _data_bus))


# 初始化（gunicorn import 时自动执行）
init_push_channels()
_init_scheduler()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)