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


class WebhookPush(PushChannel):
    def __init__(self, url: str, auth_token: str = None, channel_id: str = None):
        self._url = url
        self._auth_token = auth_token
        self._channel_id = channel_id

    def send(self, title: str, content: str) -> bool:
        try:
            payload = {
                "text": f"【量化日报】{title}\n\n{content}",
                "channelId": self._channel_id or "quant",
            }
            headers = {"Content-Type": "application/json"}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"
            resp = requests.post(self._url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 202):
                logger.info(f"Webhook 推送成功: {title}")
                return True
            else:
                logger.error(f"Webhook 推送失败: {resp.status_code} {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Webhook 推送异常: {e}")
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


# 综合链条 → 关键品种（data_dep, 显示名）
# 每个链条只列最重要的，避免信息过载
_KEY_ASSETS = {
    'full_meat_chain': [
        ('pork_futures', '生猪'),       # 核心品种
        ('egg_futures', '鸡蛋'),         # 替代品
        ('soybean_meal_futures', '豆粕'), # 主要饲料成本
        ('corn_futures', '玉米'),         # 主要饲料成本
    ],
    'energy_chain': [
        ('crude_oil_futures', '原油'),     # 核心品种
        ('natural_gas_futures', '天然气'), # 替代能源
    ],
    'metals_chain': [
        ('gold_futures', '黄金'),          # 必选
        ('silver_futures', '白银'),        # 必选
        ('copper_futures', '铜'),           # 经济晴雨表
        ('iron_ore_futures', '铁矿石'),    # 螺纹钢成本核心
    ],
    'macro_chain': [
        ('vix', 'VIX恐慌指数'),             # 风险情绪
        ('usd_cny', '美元/人民币'),        # 汇率
    ],
}


def _get_close_prices(data_bus, data_dep: str) -> Optional[List[float]]:
    """读取并清洗收盘价序列。"""
    try:
        df = data_bus.get(data_dep)
        if df is None or df.empty or 'close' not in df.columns:
            return None
        prices = []
        for value in df['close'].dropna().tolist():
            try:
                prices.append(float(value))
            except (TypeError, ValueError):
                continue
        return prices or None
    except Exception:
        return None


def _get_price_trend(data_bus, data_dep: str, days: int = 5) -> Optional[List[float]]:
    """获取最近 N 天的收盘价列表。"""
    prices = _get_close_prices(data_bus, data_dep)
    if not prices or len(prices) < 2:
        return None
    return prices[-days:]


def _format_trend(prices: list) -> str:
    """格式化价格趋势，带方向箭头"""
    if not prices or len(prices) < 2:
        return ""
    arrow = "↑" if prices[-1] > prices[0] else ("↓" if prices[-1] < prices[0] else "→")
    # 涨跌幅
    pct = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0
    price_str = " → ".join(f"{p:.0f}" if abs(p) >= 100 else f"{p:.2f}" for p in prices)
    return f"{price_str} {arrow} ({pct:+.1f}%)"


def _period_label(days: int) -> str:
    if days >= 200:
        return "近1年"
    if days >= 100:
        return "近半年"
    if days >= 40:
        return "近2个月"
    return f"近{days}天"


def _position_label(percentile: float) -> str:
    if percentile <= 20:
        return "接近底部区间"
    if percentile <= 40:
        return "偏低区间"
    if percentile <= 60:
        return "中等水平"
    if percentile <= 80:
        return "偏高区间"
    return "接近顶部区间"


def _get_price_position(data_bus, data_dep: str, lookback_days: int = 250) -> Optional[Dict[str, Any]]:
    """计算当前价格在历史中的分位位置。"""
    prices = _get_close_prices(data_bus, data_dep)
    if not prices or len(prices) < 20:
        return None

    hist = prices[-lookback_days:]
    current = prices[-1]
    percentile = float(sum(price < current for price in hist) / len(hist) * 100)

    return {
        "percentile": round(percentile, 1),
        "current_price": current,
        "sample_days": len(hist),
    }


def _format_price_position(data_bus, data_dep: str, lookback_days: int = 250) -> str:
    """格式化历史价格位置描述"""
    pos = _get_price_position(data_bus, data_dep, lookback_days)
    if pos is None:
        return ""
    
    cheaper_pct = pos["percentile"]
    period = _period_label(pos["sample_days"])
    label = _position_label(cheaper_pct)

    return f"📍 {period}：仅{cheaper_pct:.0f}%的交易日比现在更便宜（{label}）"


def format_signal_report(composite_results: Dict[str, Any], data_bus=None) -> str:
    """Format composite chain results as markdown for push messages.

    Delegates to core.report_formatter for the canonical structure, then
    enriches with price context from data_bus.
    """
    from core.report_formatter import format_chain_report, format_chain_report_markdown, format_trend, period_label, position_label

    report = format_chain_report(composite_results)

    # Build price context if data_bus is available
    price_context = []
    if data_bus is not None:
        chain_name = composite_results.get("chain", "")
        key_assets = _KEY_ASSETS.get(chain_name, [])
        for data_dep, label in key_assets:
            prices = _get_price_trend(data_bus, data_dep)
            trend_str = format_trend(prices) if prices else ""
            pos = _get_price_position(data_bus, data_dep)
            pos_str = ""
            if pos:
                pct = pos["percentile"]
                lbl = position_label(pct)
                period = period_label(pos["sample_days"])
                pos_str = f"📍 {period}：仅{pct:.0f}%的交易日比现在更便宜（{lbl}）"
            if trend_str:
                price_context.append({"label": label, "trend": trend_str, "position": pos_str})

    return format_chain_report_markdown(report, price_context=price_context or None)


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
        elif ch_type == "webhook":
            url = ch_cfg.get("url", "")
            auth_token = ch_cfg.get("auth_token")
            channel_id = ch_cfg.get("channel_id")
            if url:
                manager.add_channel(WebhookPush(url, auth_token, channel_id))
                logger.info(f"已配置 Webhook 推送: {url[:50]}...")
        elif ch_type == "console":
            manager.add_channel(ConsolePush())
            logger.info("已配置控制台输出")

    if not manager._channels:
        manager.add_channel(ConsolePush())
        logger.warning("推送渠道配置无效，回退到控制台输出")