"""监控类路由：信号历史、IC 分析、回测。"""
from flask import jsonify, request
from datetime import datetime
import logging

from routes import monitoring_bp

logger = logging.getLogger(__name__)


def _get_services():
    """从 current_app 获取服务实例。"""
    from flask import current_app
    app = current_app._get_current_object()
    return {
        'chains_config': app.chains_config,
        'runner': app.runner,
        'data_bus': app.data_bus,
        'signal_logger': app.signal_logger,
        'ic_monitor': app.ic_monitor,
    }


@monitoring_bp.route('/signals/history', methods=['GET'])
def signal_history():
    svc = _get_services()
    signal_logger = svc['signal_logger']
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


@monitoring_bp.route('/signals/stats', methods=['GET'])
def signal_stats():
    svc = _get_services()
    signal_logger = svc['signal_logger']
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


@monitoring_bp.route('/ic/<factor_name>', methods=['GET'])
def ic_analysis(factor_name):
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    data_bus = svc['data_bus']
    ic_monitor = svc['ic_monitor']
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


@monitoring_bp.route('/ic/health', methods=['GET'])
def ic_health_report():
    svc = _get_services()
    runner = svc['runner']
    ic_monitor = svc['ic_monitor']
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


@monitoring_bp.route('/trigger_backtest', methods=['GET'])
def trigger_backtest_endpoint():
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    data_bus = svc['data_bus']
    signal_logger = svc['signal_logger']
    runner.ensure_imported()
    days = int(request.args.get('days', 365))
    min_samples = int(request.args.get('min_samples', 3))
    from evaluation.trigger_backtest import trigger_backtest
    return jsonify(trigger_backtest(chains_config, data_bus, signal_logger, days=days, min_samples=min_samples))


@monitoring_bp.route('/recommendation_backtest', methods=['GET'])
def recommendation_backtest_endpoint():
    """建议有效性验证：评估买入/卖出/观望建议的历史表现。"""
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    data_bus = svc['data_bus']
    signal_logger = svc['signal_logger']
    runner.ensure_imported()
    days = int(request.args.get('days', 365))
    min_samples = int(request.args.get('min_samples', 3))

    from evaluation.trigger_backtest import trigger_backtest
    bt_result = trigger_backtest(chains_config, data_bus, signal_logger, days=days, min_samples=min_samples)

    triggers = bt_result.get("triggers", {})
    buy_eval = []
    sell_eval = []

    for name, stats in triggers.items():
        if stats.get("insufficient_samples"):
            continue
        direction = "BUY" if "buy" in name.lower() else ("SELL" if "sell" in name.lower() else "HOLD")
        entry = {
            "trigger": name,
            "count": stats.get("count", 0),
            "asset": stats.get("asset", ""),
            "description": stats.get("description", ""),
            "returns": {},
        }
        for h in [1, 5, 10, 20]:
            avg_key = f"avg_fwd_{h}d"
            wr_key = f"win_rate_fwd_{h}d"
            if stats.get(avg_key) is not None:
                entry["returns"][f"{h}d"] = {
                    "avg_return": stats[avg_key],
                    "win_rate": stats.get(wr_key),
                }
        if direction == "BUY":
            buy_eval.append(entry)
        else:
            sell_eval.append(entry)

    return jsonify({
        "summary": bt_result.get("summary", {}),
        "buy_recommendations": buy_eval,
        "sell_recommendations": sell_eval,
        "note": "建议有效性验证口径: 不做账户净值、不做持仓模拟",
        "timestamp": datetime.now().isoformat(),
    })
