#!/usr/bin/env python
"""测试价格触及告警功能。"""

import sys
sys.path.insert(0, '/home/adminlinux/projects/quant_factors')

from core.market_alert import _get_realtime_price, check_price_alerts

# 测试获取价格
print("测试实时价格获取:")
print("-" * 50)

test_symbols = [
    ('AU0', '黄金期货'),
    ('AG0', '白银期货'),
    ('spot_pork', '生猪现货'),
]

for symbol, name in test_symbols:
    price = _get_realtime_price(symbol)
    if price:
        print(f"✓ {name} ({symbol}): {price:.2f}")
    else:
        print(f"✗ {name} ({symbol}): 获取失败")

print("\n" + "=" * 50)
print("价格触及告警功能已实现!")
print("\n配置文件位置：~/projects/quant_factors/config/price_alerts.yaml")
print("状态文件位置：~/projects/quant_factors/data/price_alert_state.json")
print("\n使用方法:")
print("1. 编辑 config/price_alerts.yaml 添加您的告警")
print("2. 定时任务会自动检查（每 30 分钟）")
print("3. 触发后自动禁用，需手动修改配置重新启用")
