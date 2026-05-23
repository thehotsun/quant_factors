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


def create_app(settings=None):
    """App factory：创建并配置 Flask app 及所有服务。

    Args:
        settings: 可选覆盖配置 dict，用于测试注入。
            支持的 key: data_dir, signals_db_path, ic_db_path

    Returns:
        配置好的 Flask app 实例。
    """
    app = Flask(__name__)

    # 加载配置（允许测试覆盖）
    data_dir = (settings or {}).get("data_dir", DATA_DIR)
    signals_db_path = (settings or {}).get("signals_db_path", SIGNALS_DB_PATH)
    ic_db_path = (settings or {}).get("ic_db_path", IC_DB_PATH)

    # 链条配置
    try:
        chains_config = load_chains_config()
        FactorRegistry.sync_from_chains(chains_config)
    except Exception as e:
        raise SystemExit(f"无法加载 chains.yaml: {e}")

    chain_defs = build_chain_definitions(chains_config, registry_info_fn=FactorRegistry.info)
    metadata_diffs = check_metadata_consistency(chains_config, FactorRegistry.info)
    if metadata_diffs:
        for d in metadata_diffs:
            logger.warning("链条 %s 字段 %s 不一致: yaml=%r registry=%r", d.chain, d.field, d.yaml_value, d.registry_value)

    # 服务实例
    data_bus = DataBus(str(data_dir))
    signal_logger = SignalLogger(str(signals_db_path))
    ic_monitor = ICMonitor(str(ic_db_path))
    factor_params = load_factor_params()
    runner = FactorRunner(chains_config, factor_params, data_dir, signal_logger, ic_monitor, chain_defs=chain_defs)

    # 挂到 app 上供路由访问
    app.chains_config = chains_config
    app.chain_defs = chain_defs
    app.data_bus = data_bus
    app.signal_logger = signal_logger
    app.ic_monitor = ic_monitor
    app.runner = runner

    # ── 路由注册 ──────────────────────────────────────────────

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"status": "ok"})

    @app.route('/analyze/<chain>', methods=['GET'])
    def analyze_auto(chain):
        runner.ensure_imported()
        cfg = chains_config.get(chain)
        if cfg:
            if cfg.get("category") == "composite":
                return _run_composite_chain(chain)
            result = runner.run_chain(chain)
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
            chain_name, chains_config, runner.run_chain,
            ensure_imported=runner.ensure_imported,
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
        runner.ensure_imported()
        chain_list = []
        for name, cfg in chains_config.items():
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
        runner.ensure_imported()
        result = runner.calculate_only(chain_name)
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
        runner.ensure_imported()
        factors = FactorRegistry.list_all()
        return jsonify({"factors": factors, "total": len(factors)})

    @app.route('/signal/<chain_name>', methods=['GET'])
    def signal_only(chain_name):
        runner.ensure_imported()
        result = runner.signal_only(chain_name)
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
        rows = signal_logger.query(
            factor_name=factor_name, days=days, limit=limit,
            as_of=as_of, run_id=run_id, trigger=trigger, direction=direction,
        )
        return jsonify({
            "signals": rows,
            "count": len(rows),
            "query": {
                "factor": factor_name, "days": days, "limit": limit,
                "as_of": as_of, "run_id": run_id, "trigger": trigger, "direction": direction,
            },
        })

    @app.route('/signals/stats', methods=['GET'])
    def signal_stats():
        factor_name = request.args.get('factor')
        days = int(request.args.get('days', 90))
        as_of = request.args.get('as_of')
        run_id = request.args.get('run_id')
        trigger = request.args.get('trigger')
        direction = request.args.get('direction')
        return jsonify(signal_logger.stats(
            factor_name=factor_name, days=days,
            as_of=as_of, run_id=run_id, trigger=trigger, direction=direction,
        ))

    @app.route('/ic/<factor_name>', methods=['GET'])
    def ic_analysis(factor_name):
        runner.ensure_imported()
        cfg = chains_config.get(factor_name)
        if not cfg:
            return jsonify({"error": f"unknown factor: {factor_name}"}), 400
        data_deps = cfg.get("data_deps", [])
        price_df = None
        for dep in data_deps:
            df = data_bus.get(dep)
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
        result = ic_monitor.compute_ic(factor_name, price_df, forward_days=forward_days, window=window)
        if result is None:
            return jsonify({
                "factor_name": factor_name,
                "error": "insufficient snapshot data",
                "note": "因子快照数据不足，需要积累更多天的数据"
            })
        result["decay"] = ic_monitor.get_decay_status(factor_name)
        result["ic_history"] = ic_monitor.get_ic_history(factor_name, days=90)
        return jsonify(result)

    @app.route('/ic/health', methods=['GET'])
    def ic_health_report():
        runner.ensure_imported()
        report = ic_monitor.health_report()
        decayed = [r for r in report if r.get("trend") in ("severe_decay", "moderate_decay")]
        warning = [r for r in report if r.get("trend") == "mild_decay"]
        healthy = [r for r in report if r.get("trend") == "stable"]
        return jsonify({
            "report": report,
            "summary": {
                "total": len(report), "healthy": len(healthy),
                "warning": len(warning), "decayed": len(decayed),
            },
            "decayed_factors": [r["factor_name"] for r in decayed],
            "timestamp": datetime.now().isoformat()
        })

    @app.route('/trigger_backtest', methods=['GET'])
    def trigger_backtest_endpoint():
        runner.ensure_imported()
        days = int(request.args.get('days', 365))
        min_samples = int(request.args.get('min_samples', 3))
        return jsonify(trigger_backtest(chains_config, data_bus, signal_logger, days=days, min_samples=min_samples))

    @app.route('/push/<chain_name>', methods=['GET'])
    def push_chain(chain_name):
        runner.ensure_imported()
        if chain_name not in chains_config:
            return jsonify({"error": f"unknown chain: {chain_name}"}), 400
        cfg = chains_config[chain_name]
        if cfg.get("category") == "composite":
            result = _run_composite_chain(chain_name)
        else:
            factor_result = runner.run_chain(chain_name)
            result = jsonify({
                "chain": chain_name,
                "description": cfg.get("description", ""),
                "active_signals": [factor_result["opportunity"]] if factor_result and factor_result.get("opportunity") else [],
                "signal_count": 1 if factor_result and factor_result.get("opportunity") else 0,
                "aggregated_signal": factor_result.get("opportunity") if factor_result else None,
                "all_results": {chain_name: factor_result} if factor_result else {},
                "timestamp": datetime.now().isoformat()
            })
        return jsonify(send_chain_push(chain_name, cfg, result, data_bus))

    # ── 定时任务 ──────────────────────────────────────────────

    def _daily_data_refresh():
        return daily_data_refresh(data_bus)

    def _daily_data_refresh_foreign():
        return daily_data_refresh_foreign(data_bus)

    def _daily_ic_compute():
        return compute_daily_ic(chains_config, data_bus, ic_monitor, runner.ensure_imported)

    def _daily_push():
        return push_daily_composite_reports(app, chains_config, _run_composite_chain, data_bus)

    # 仅在非测试模式下初始化 push 和 scheduler
    if not (settings or {}).get("skip_scheduler"):
        init_push_channels()
        init_scheduler(
            _daily_data_refresh, _daily_data_refresh_foreign,
            _daily_ic_compute, _daily_push,
        )

    return app


# ── 向后兼容：gunicorn import 时自动创建 app ──────────────────
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
