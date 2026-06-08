"""展示单位换算工具。

底层数据保持原样（期货交易所原始报价单位），仅在展示时换算为更直观的单位。

规则：
- 农产品（生猪、鸡蛋、鸡肉等）→ 斤
- 贵金属（黄金、白银）→ 克
- 其他品种 → 保持原单位

用法：
    from core.display_units import display_price, display_unit_label
    display_price('silver_futures', 18358)  # → "18.36"
    display_unit_label('silver_futures')     # → "元/克"
"""
from __future__ import annotations

from typing import Optional, Tuple

# ── 换算规则 ──────────────────────────────────────────────
# data_dep 或 symbol → (除数, 展示单位)
# 除数：原始价格 / 除数 = 展示价格

_DISPLAY_RULES = {
    # 贵金属：元/千克 → 元/克
    "silver_futures": (1000, "元/克"),
    "silver_spot": (1000, "元/克"),
    "gold_futures": (1, "元/克"),       # 黄金本身就是元/克
    "gold_spot": (1, "元/克"),

    # 生猪：元/吨 → 元/斤
    "pork_futures": (2000, "元/斤"),
    "pork_spot": (2000, "元/斤"),

    # 鸡蛋：元/500千克 → 元/斤
    "egg_futures": (1000, "元/斤"),
    "egg_spot": (1000, "元/斤"),

    # 鸡肉：元/吨 → 元/斤（如有）
    "chicken_futures": (2000, "元/斤"),
    "chicken_spot": (2000, "元/斤"),

    # 农产品现货（market_alert.py 使用 spot_ 前缀）
    "spot_corn": (2000, "元/斤"),
    "spot_soybean_domestic": (2000, "元/斤"),
    "spot_pork": (2000, "元/斤"),
}

# akshare 新浪代码映射（市场告警用）
_SYMBOL_RULES = {
    "AG0": (1000, "元/克"),   # 白银期货
    "AU0": (1, "元/克"),      # 黄金期货
    "LH0": (2000, "元/斤"),   # 生猪期货
    "JD0": (1000, "元/斤"),   # 鸡蛋期货
}


def get_display_rule(key: str) -> Optional[Tuple[float, str]]:
    """获取展示换算规则。

    Args:
        key: data_dep 名称（如 'silver_futures'）或新浪代码（如 'AG0'）

    Returns:
        (除数, 展示单位) 或 None（无需换算）
    """
    return _DISPLAY_RULES.get(key) or _SYMBOL_RULES.get(key)


def display_price(key: str, raw_price: float, fmt: str = "auto") -> str:
    """将原始价格换算为展示价格字符串。

    Args:
        key: data_dep 或 symbol
        raw_price: 原始价格
        fmt: 格式化方式
            - "auto": 自动选择小数位数
            - ".0f": 整数
            - ".1f": 1位小数
            - ".2f": 2位小数

    Returns:
        展示价格字符串
    """
    rule = get_display_rule(key)
    if rule:
        divisor, _ = rule
        price = raw_price / divisor
    else:
        price = raw_price

    if fmt == "auto":
        if abs(price) >= 100:
            return f"{price:,.0f}"
        elif abs(price) >= 1:
            return f"{price:.2f}"
        else:
            return f"{price:.4f}"
    else:
        return f"{price:{fmt}}"


def display_unit_label(key: str, fallback: str = "") -> str:
    """获取展示单位标签。

    Args:
        key: data_dep 或 symbol

    Returns:
        展示单位字符串，如 "元/克"、"元/斤"
    """
    rule = get_display_rule(key)
    if rule:
        return rule[1]
    return fallback


def display_price_with_unit(key: str, raw_price: float, fmt: str = "auto") -> str:
    """价格 + 单位一起返回。

    Returns:
        如 "18.36 元/克"、"6.04 元/斤"
    """
    price_str = display_price(key, raw_price, fmt)
    unit = display_unit_label(key)
    if unit:
        return f"{price_str} {unit}"
    return price_str
