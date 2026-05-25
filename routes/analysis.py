"""分析类路由：链条分析、因子数据、信号、建议、每日总览。"""
from flask import jsonify, request
from datetime import datetime
import logging

from routes import analysis_bp

logger = logging.getLogger(__name__)


def _get_services():
    """从 current_app 获取服务实例。"""
    from flask import current_app
    app = current_app._get_current_object()
    return {
        'chains_config': app.chains_config,
        'chain_defs': app.chain_defs,
        'runner': app.runner,
        'data_bus': app.data_bus,
        'signal_logger': app.signal_logger,
    }


@analysis_bp.route('/analyze/<chain>', methods=['GET'])
def analyze_auto(chain):
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
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
                "chain_meta": result.get("chain_meta"),
                "timestamp": datetime.now().isoformat()
            })
    return jsonify({"error": f"unknown chain: {chain}"}), 400


def _run_composite_chain(chain_name):
    svc = _get_services()
    from core.composite_runner import run_composite_chain
    return jsonify(run_composite_chain(
        chain_name, svc['chains_config'], svc['runner'].run_chain,
        ensure_imported=svc['runner'].ensure_imported,
    ))


@analysis_bp.route('/analyze/full_meat_chain', methods=['GET'])
def full_meat_chain():
    return _run_composite_chain("full_meat_chain")


@analysis_bp.route('/analyze/energy', methods=['GET'])
def energy_chain():
    return _run_composite_chain("energy_chain")


@analysis_bp.route('/analyze/metals', methods=['GET'])
def metals_chain():
    return _run_composite_chain("metals_chain")


@analysis_bp.route('/analyze/macro', methods=['GET'])
def macro_chain():
    return _run_composite_chain("macro_chain")


@analysis_bp.route('/factor/<chain_name>', methods=['GET'])
def factor_data(chain_name):
    svc = _get_services()
    runner = svc['runner']
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


@analysis_bp.route('/signal/<chain_name>', methods=['GET'])
def signal_only(chain_name):
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    runner.ensure_imported()
    result = runner.signal_only(chain_name)
    if result is None:
        return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
    if result.get("error"):
        return jsonify({"error": result["error"], "error_type": result.get("error_type", "")}), 500
    chain_meta = runner._chain_meta(chain_name)
    from core.recommendation_engine import RecommendationEngine
    rec = RecommendationEngine.from_signal({
        **result,
        "chain_meta": chain_meta,
    })
    return jsonify({
        "chain": chain_name,
        "signal": result.get("signal"),
        "signal_strength": result.get("signal_strength"),
        "chain_meta": chain_meta,
        "recommendation": rec,
        "timestamp": datetime.now().isoformat()
    })


@analysis_bp.route('/recommend/<chain_name>', methods=['GET'])
def recommend(chain_name):
    """纯净建议接口：输出 BUY/SELL/HOLD 建议，不涉及持仓或交易。"""
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    data_bus = svc['data_bus']
    runner.ensure_imported()
    cfg = chains_config.get(chain_name)
    if cfg is None:
        return jsonify({"error": f"unknown chain: {chain_name}"}), 400

    from core.recommendation_engine import RecommendationEngine
    if cfg.get("category") == "composite":
        from core.composite_runner import run_composite_chain
        composite_result = run_composite_chain(
            chain_name, chains_config, runner.run_chain,
            ensure_imported=runner.ensure_imported,
        )
        if hasattr(composite_result, 'get_json'):
            composite_data = composite_result.get_json()
        else:
            composite_data = composite_result
        aggregated = composite_data.get("aggregated_signal")
        chain_meta = {"chain": chain_name, "category": "composite"}
        rec = RecommendationEngine.from_aggregated(aggregated, chain_meta)
    else:
        result = runner.run_chain(chain_name)
        if result is None:
            return jsonify({"error": f"no factor module for chain: {chain_name}"}), 400
        if result.get("error"):
            return jsonify({"error": result["error"], "error_type": result.get("error_type", "")}), 500
        chain_meta = runner._chain_meta(chain_name)
        rec = RecommendationEngine.from_signal({
            **result,
            "chain_meta": chain_meta,
        })

    return jsonify({
        "chain": chain_name,
        "description": cfg.get("description", ""),
        "recommendation": rec,
        "price_context": _build_price_context(chain_name, data_bus),
        "timestamp": datetime.now().isoformat(),
    })


def _build_price_context(chain_name: str, data_bus):
    """Build spot + futures price context for a chain."""
    from core.push import _SPOT_FUTURES_PAIRS, _get_price_trend, _get_price_position, _format_trend, _position_label, _period_label
    pair = _SPOT_FUTURES_PAIRS.get(chain_name)
    if not pair:
        return None
    futures_dep, spot_dep, label = pair
    context = []
    prices = _get_price_trend(data_bus, futures_dep)
    if prices:
        trend = _format_trend(prices)
        pos = _get_price_position(data_bus, futures_dep)
        pos_str = ""
        if pos:
            pct = pos["percentile"]
            lbl = _position_label(pct)
            period = _period_label(pos["sample_days"])
            pos_str = f"📍 {period}：仅{pct:.0f}%的交易日比现在更便宜（{lbl}）"
        context.append({"label": f"{label}期货", "trend": trend, "position": pos_str})
    if spot_dep:
        spot_prices = _get_price_trend(data_bus, spot_dep)
        if spot_prices:
            spot_trend = _format_trend(spot_prices)
            context.append({"label": f"{label}现货", "trend": spot_trend, "position": ""})
    return context if context else None


@analysis_bp.route('/recommendations/daily', methods=['GET'])
def daily_overview():
    """每日总览：返回所有链条今日的建议列表。"""
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    runner.ensure_imported()
    from core.recommendation_engine import RecommendationEngine

    buy_list = []
    sell_list = []
    hold_list = []
    data_issues = []

    for chain_name, cfg in chains_config.items():
        if cfg.get("category") == "composite":
            continue
        try:
            result = runner.run_chain(chain_name)
            if result is None:
                continue
            if result.get("error"):
                continue
            chain_meta = runner._chain_meta(chain_name)
            rec = RecommendationEngine.from_signal({
                **result,
                "chain_meta": chain_meta,
            })
            entry = {
                "chain": chain_name,
                "description": cfg.get("description", ""),
                "recommendation": rec["recommendation"],
                "label": rec["label"],
                "strength": rec["strength"],
                "confidence": rec["confidence"],
                "reason": rec["reason"],
            }
            if rec["recommendation"] == "BUY":
                buy_list.append(entry)
            elif rec["recommendation"] == "SELL":
                sell_list.append(entry)
            else:
                hold_list.append(entry)
            if rec["missing_drivers"] or rec["data_notes"]:
                data_issues.append({
                    "chain": chain_name,
                    "missing_drivers": rec["missing_drivers"],
                    "data_notes": rec["data_notes"],
                })
        except Exception as e:
            logger.warning("daily_overview: %s 失败: %s", chain_name, e)

    return jsonify({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "buy": buy_list,
        "sell": sell_list,
        "hold": hold_list,
        "data_issues": data_issues,
        "summary": {
            "total": len(buy_list) + len(sell_list) + len(hold_list),
            "buy_count": len(buy_list),
            "sell_count": len(sell_list),
            "hold_count": len(hold_list),
            "data_issue_count": len(data_issues),
        },
        "timestamp": datetime.now().isoformat(),
    })
