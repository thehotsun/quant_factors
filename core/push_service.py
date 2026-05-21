"""Push/report helpers for quant_factors."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

from core.push import get_push_manager, format_signal_report

logger = logging.getLogger(__name__)


def build_chain_push_payload(chain_name: str, cfg: Dict[str, Any], run_result: Dict[str, Any], data_bus) -> str:
    """Format a chain result into the standard push markdown body."""
    if hasattr(run_result, 'get_json'):
        result_data = run_result.get_json()
    else:
        result_data = run_result
    content = format_signal_report(result_data, data_bus)
    return content


def send_chain_push(chain_name: str, cfg: Dict[str, Any], run_result: Dict[str, Any], data_bus) -> Dict[str, Any]:
    """Send a single chain report through configured push channels."""
    content = build_chain_push_payload(chain_name, cfg, run_result, data_bus)
    title = f"量化分析 - {chain_name}"
    push_mgr = get_push_manager()
    push_result = push_mgr.send(title, content)
    return {
        "chain": chain_name,
        "push_result": push_result,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    }


def push_daily_composite_reports(app, chains_config, run_composite_chain, data_bus) -> int:
    """Send daily reports for all composite chains.

    Returns the number of successful chain pushes.
    """
    logger.info("开始每日分析推送...")
    with app.app_context():
        composite_chains = [name for name, cfg in chains_config.items() if cfg.get("category") == "composite"]
        if not composite_chains:
            logger.warning("未配置综合链条，跳过推送")
            return 0

        push_mgr = get_push_manager()
        success_count = 0
        for chain_name in composite_chains:
            try:
                result = run_composite_chain(chain_name)
                if hasattr(result, 'get_json'):
                    result_data = result.get_json()
                else:
                    result_data = json.loads(result.get_data(as_text=True))
                content = format_signal_report(result_data, data_bus)
                title = f"量化分析日报 - {chain_name}"
                push_result = push_mgr.send(title, content)
                if any(push_result.values()):
                    success_count += 1
            except Exception as e:
                logger.error("推送 %s 失败: %s", chain_name, e)

        logger.info("每日推送完成: %d/%d 个链条推送成功", success_count, len(composite_chains))
        return success_count
