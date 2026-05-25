"""推送类路由：手动触发推送。"""
from flask import jsonify
import logging

from routes import push_bp

logger = logging.getLogger(__name__)


def _get_services():
    """从 current_app 获取服务实例。"""
    from flask import current_app
    app = current_app._get_current_object()
    return {
        'chains_config': app.chains_config,
        'runner': app.runner,
        'data_bus': app.data_bus,
    }


@push_bp.route('/push/<chain_name>', methods=['GET'])
def push_chain(chain_name):
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
    data_bus = svc['data_bus']
    runner.ensure_imported()
    if chain_name not in chains_config:
        return jsonify({"error": f"unknown chain: {chain_name}"}), 400
    cfg = chains_config[chain_name]
    if cfg.get("category") == "composite":
        from core.composite_runner import run_composite_chain
        result = jsonify(run_composite_chain(
            chain_name, chains_config, runner.run_chain,
            ensure_imported=runner.ensure_imported,
        ))
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
    from core.push_service import send_chain_push
    return jsonify(send_chain_push(chain_name, cfg, result, data_bus))
