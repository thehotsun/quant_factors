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
from core.recommendation_engine import RecommendationEngine

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

    # ── 注册 Blueprint 路由 ──────────────────────────────────
    from routes import analysis_bp, monitoring_bp, system_bp, push_bp
    app.register_blueprint(system_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(push_bp)

    # ── 定时任务（非交易日自动跳过）────────────────────────────

    from core.trading_calendar import is_trading_day

    def _daily_data_refresh():
        if not is_trading_day():
            logger.info("今天 (%s) 非交易日，跳过国内数据刷新", datetime.now().date())
            return None
        return daily_data_refresh(data_bus)

    def _daily_data_refresh_foreign():
        if not is_trading_day():
            logger.info("今天 (%s) 非交易日，跳过外盘数据刷新", datetime.now().date())
            return None
        return daily_data_refresh_foreign(data_bus)

    def _daily_ic_compute():
        if not is_trading_day():
            logger.info("今天 (%s) 非交易日，跳过IC计算", datetime.now().date())
            return None
        return compute_daily_ic(chains_config, data_bus, ic_monitor, runner.ensure_imported)

    def _daily_push():
        if not is_trading_day():
            logger.info("今天 (%s) 非交易日，跳过每日推送", datetime.now().date())
            return None
        return push_daily_composite_reports(app, chains_config, _run_composite_chain_for_push, data_bus)

    def _run_composite_chain_for_push(chain_name):
        return jsonify(run_composite_chain(
            chain_name, chains_config, runner.run_chain,
            ensure_imported=runner.ensure_imported,
        ))

    def _market_alert():
        from core.market_alert import run_market_alert_check
        return run_market_alert_check()

    # 仅在非测试模式下初始化 push 和 scheduler
    if not (settings or {}).get("skip_scheduler"):
        init_push_channels()
        init_scheduler(
            _daily_data_refresh, _daily_data_refresh_foreign,
            _daily_ic_compute, _daily_push,
            market_alert=_market_alert,
        )

    return app


# ── 向后兼容：gunicorn import 时自动创建 app ──────────────────
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
