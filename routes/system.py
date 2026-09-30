"""系统类路由：健康检查、链条列表、因子注册表、驱动健康。"""
from flask import jsonify
import logging

from routes import system_bp

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
    }


@system_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


@system_bp.route('/freshness', methods=['GET'])
def freshness():
    """数据新鲜度巡检（不推送），供监控与手动测试。"""
    from core.data_refresh import check_data_freshness
    problems = check_data_freshness(push=False)
    return jsonify({"ok": not problems, "problems": problems})


@system_bp.route('/sources', methods=['GET'])
def sources():
    """数据源容灾状态：源链配置 + 最近一次取数/探测结果（哪几个源能通）。

    加 `?probe=1` 对所有源做一次实时探测（较慢，会联网）。
    """
    from flask import request
    from core.source_chain import load_source_config, read_status, probe_all
    cfg = load_source_config()
    if str(request.args.get("probe", "")).lower() in ("1", "true", "yes"):
        try:
            probe_all()
        except Exception as e:  # noqa: BLE001
            logger.warning("数据源探测失败: %s", e)
    status = read_status()
    return jsonify({
        "config": cfg.get("datasets", {}),
        "status": status.get("datasets", {}),
        "updated_at": status.get("updated_at"),
    })


@system_bp.route('/chains', methods=['GET'])
def list_chains():
    svc = _get_services()
    runner = svc['runner']
    chains_config = svc['chains_config']
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


@system_bp.route('/registry', methods=['GET'])
def list_registry():
    svc = _get_services()
    runner = svc['runner']
    runner.ensure_imported()
    from core.factor_registry import FactorRegistry
    factors = FactorRegistry.list_all()
    return jsonify({"factors": factors, "total": len(factors)})


@system_bp.route('/driver_health', methods=['GET'])
@system_bp.route('/driver_health/<chain_name>', methods=['GET'])
def driver_health(chain_name=None):
    svc = _get_services()
    runner = svc['runner']
    chain_defs = svc['chain_defs']
    data_bus = svc['data_bus']
    runner.ensure_imported()
    if chain_name:
        chain_def = chain_defs.get(chain_name)
        if chain_def is None:
            return jsonify({"error": f"unknown chain: {chain_name}"}), 400
        drivers = getattr(chain_def, "drivers", {})
        if not drivers:
            return jsonify({"chain": chain_name, "drivers": {}, "message": "non-mixed chain"})
        status = data_bus.get_driver_status(chain_def)
        return jsonify({"chain": chain_name, "drivers": status})
    result = {}
    for name, chain_def in chain_defs.items():
        drivers = getattr(chain_def, "drivers", {})
        if drivers:
            result[name] = data_bus.get_driver_status(chain_def)
    return jsonify({"chains": result, "total": len(result)})
