import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)


class PushChannel:
    def send(self, title: str, content: str) -> bool:
        raise NotImplementedError


class ConsolePush(PushChannel):
    def send(self, title: str, content: str) -> bool:
        logger.info(f"[推送] {title}\n{content}")
        return True


class DingTalkPush(PushChannel):
    def __init__(self, webhook_url: str, secret: str = None):
        self._webhook_url = webhook_url
        self._secret = secret

    def send(self, title: str, content: str) -> bool:
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"## {title}\n\n{content}\n\n> 发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            }
            url = self._webhook_url
            if self._secret:
                import time
                import hmac
                import hashlib
                import base64
                import urllib.parse
                timestamp = str(round(time.time() * 1000))
                secret_enc = self._secret.encode('utf-8')
                string_to_sign = f'{timestamp}\n{self._secret}'
                string_to_sign_enc = string_to_sign.encode('utf-8')
                hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                url = f"{self._webhook_url}&timestamp={timestamp}&sign={sign}"

            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("errcode") == 0:
                    logger.info("钉钉推送成功")
                    return True
                else:
                    logger.error(f"钉钉推送失败: {result}")
                    return False
            else:
                logger.error(f"钉钉推送HTTP错误: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"钉钉推送异常: {e}")
            return False


class FeishuPush(PushChannel):
    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    def send(self, title: str, content: str) -> bool:
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": title},
                        "template": "blue"
                    },
                    "elements": [
                        {"tag": "markdown", "content": content},
                        {"tag": "note", "elements": [
                            {"tag": "plain_text", "content": f"发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                        ]}
                    ]
                }
            }
            resp = requests.post(self._webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    logger.info("飞书推送成功")
                    return True
                else:
                    logger.error(f"飞书推送失败: {result}")
                    return False
            else:
                logger.error(f"飞书推送HTTP错误: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"飞书推送异常: {e}")
            return False


class PushManager:
    def __init__(self):
        self._channels: List[PushChannel] = [ConsolePush()]

    def add_channel(self, channel: PushChannel):
        self._channels.append(channel)

    def send(self, title: str, content: str) -> Dict[str, bool]:
        results = {}
        for ch in self._channels:
            ch_name = ch.__class__.__name__
            results[ch_name] = ch.send(title, content)
        return results


def format_signal_report(composite_results: Dict[str, Any]) -> str:
    lines = []
    chain_name = composite_results.get("chain", "未知")
    description = composite_results.get("description", "")
    aggregated = composite_results.get("aggregated_signal")
    signals = composite_results.get("active_signals", [])
    all_results = composite_results.get("all_results", {})

    lines.append(f"**{chain_name}** - {description}")
    lines.append("")

    if aggregated:
        direction = aggregated.get("direction", "HOLD")
        strength = aggregated.get("strength", 0)
        confidence = aggregated.get("confidence", 0)
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(direction, "⚪")
        lines.append(f"{emoji} **综合信号: {direction}** | 强度: {strength:.2f} | 置信度: {confidence:.2f}")
        lines.append(f"信号数: {aggregated.get('signal_count', 0)} (BUY:{aggregated.get('buy_count', 0)} SELL:{aggregated.get('sell_count', 0)})")
    else:
        lines.append("⚪ 综合信号: HOLD（无有效信号）")

    if signals:
        lines.append("")
        lines.append("**活跃信号:**")
        for s in signals[:10]:
            trigger = s.get("trigger", s.get("_chain", ""))
            direction = s.get("direction", "")
            reason = s.get("reason", "")
            emoji = {"BUY": "🟢", "SELL": "🔴"}.get(direction, "")
            lines.append(f"- {emoji} **{trigger}** ({direction}): {reason[:80]}")

    errors = []
    for name, result in all_results.items():
        if isinstance(result, dict) and result.get("error"):
            errors.append(f"- {name}: {result['error']}")

    if errors:
        lines.append("")
        lines.append("**⚠️ 异常:**")
        lines.extend(errors)

    return "\n".join(lines)


_push_manager: Optional[PushManager] = None


def get_push_manager() -> PushManager:
    global _push_manager
    if _push_manager is None:
        _push_manager = PushManager()
    return _push_manager


def init_push_channels(config: Dict[str, Any] = None):
    manager = get_push_manager()
    manager._channels = []

    if config is None:
        try:
            from pathlib import Path
            import yaml
            config_path = Path(__file__).parent.parent / "config" / "push.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
            else:
                config = {}
        except Exception:
            config = {}

    channels_cfg = config.get("channels", [])
    if not channels_cfg:
        manager.add_channel(ConsolePush())
        logger.info("未配置推送渠道，使用控制台输出")
        return

    for ch_cfg in channels_cfg:
        ch_type = ch_cfg.get("type", "")
        if ch_type == "dingtalk":
            webhook = ch_cfg.get("webhook_url", "")
            secret = ch_cfg.get("secret")
            if webhook:
                manager.add_channel(DingTalkPush(webhook, secret))
                logger.info(f"已配置钉钉推送: {webhook[:50]}...")
        elif ch_type == "feishu":
            webhook = ch_cfg.get("webhook_url", "")
            if webhook:
                manager.add_channel(FeishuPush(webhook))
                logger.info(f"已配置飞书推送: {webhook[:50]}...")
        elif ch_type == "console":
            manager.add_channel(ConsolePush())

    if not manager._channels:
        manager.add_channel(ConsolePush())
        logger.warning("推送渠道配置无效，回退到控制台输出")