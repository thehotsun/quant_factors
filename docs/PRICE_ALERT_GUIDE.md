# 价格触及告警功能使用指南

## 功能概述

价格触及告警功能允许您设置特定品种的目标价格，当市场价格触及设定值时，系统会自动推送告警消息。

**核心特性：**
- ✅ 一次性触发：触及目标价后只提醒一次，避免重复骚扰
- ✅ 支持多品种：期货、现货、股票（A 股）
- ✅ 灵活条件：支持"高于"和"低于"两种触发条件
- ✅ 自动禁用：触发后自动禁用，需手动重置
- ✅ 可选自动重置：价格反向运动后可自动重新启用

## 快速开始

### 1. 添加告警配置

编辑配置文件 `~/projects/quant_factors/config/price_alerts.yaml`：

```yaml
alerts:
  - id: 1
    symbol: AU0
    name: 黄金期货
    target_price: 580
    condition: "above"
    active: true
    max_triggers: 1
    auto_reset: false
```

### 2. 等待自动检查

系统会在交易时段每 30 分钟自动检查一次（无需重启服务）。

### 3. 接收告警

当价格触及目标价时，您会收到如下推送：

```
🎯 价格触及告警 (1/1)

**黄金期货** 触及目标价
当前价：580.50 元/克
目标价：580 元/克
条件：≥ 580

⚠️ 此为一次性告警，已自动禁用
如需重新启用，请编辑配置文件并设置 active=true

时间：2026-07-22 14:30
```

## 配置参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | 整数 | ✅ | 告警唯一标识（不能重复） |
| `symbol` | 字符串 | ✅ | 品种代码（见下方代码列表） |
| `name` | 字符串 | ✅ | 品种显示名称 |
| `target_price` | 浮点数 | ✅ | 目标价格 |
| `condition` | 字符串 | ✅ | 触发条件：`above`（高于）或 `below`（低于） |
| `active` | 布尔值 | ✅ | 是否启用（`true`/`false`） |
| `max_triggers` | 整数 | ❌ | 最大触发次数（默认 1） |
| `auto_reset` | 布尔值 | ❌ | 是否自动重置（默认 `false`） |

## 品种代码列表

### 期货品种
```
AU0  - 黄金
AG0  - 白银
CU0  - 铜
AL0  - 铝
RB0  - 螺纹钢
I0   - 铁矿石
SC0  - 原油
LH0  - 生猪
JD0  - 鸡蛋
M0   - 豆粕
C0   - 玉米
A0   - 国产大豆
B0   - 进口大豆
RM0  - 菜粕
Y0   - 豆油
```

### 现货品种
```
spot_pork  - 生猪现货
spot_corn  - 玉米现货
```

### 股票（A 股）
使用股票代码，例如：
```
600519  - 贵州茅台
000001  - 平安银行
```

## 使用场景示例

### 场景 1：突破关键价位提醒
```yaml
- id: 1
  symbol: AU0
  name: 黄金期货
  target_price: 580
  condition: "above"
  active: true
  max_triggers: 1
```
→ 黄金突破 580 时提醒一次

### 场景 2：跌破支撑位提醒
```yaml
- id: 2
  symbol: 600519
  name: 贵州茅台
  target_price: 1800
  condition: "below"
  active: true
  max_triggers: 1
```
→ 茅台跌破 1800 时提醒一次

### 场景 3：多次触发监控（需手动重置）
```yaml
- id: 3
  symbol: AG0
  name: 白银期货
  target_price: 7500
  condition: "below"
  active: true
  max_triggers: 1
  auto_reset: true  # 价格反弹后自动重置
```
→ 白银跌破 7500 提醒，价格反弹回 7650 以上后可再次触发

## 状态管理

### 查看告警状态
```bash
cat ~/projects/quant_factors/data/price_alert_state.json
```

状态文件格式：
```json
{
  "1": {
    "trigger_count": 1,
    "last_triggered_at": "2026-07-22T14:30:00",
    "last_price": 580.50,
    "active": false
  }
}
```

### 重置告警

触发后的告警会自动设置 `active: false`，如需重新启用：

1. 编辑配置文件 `config/price_alerts.yaml`
2. 将对应告警的 `active` 改为 `true`
3. （可选）删除 `data/price_alert_state.json` 中对应状态

## 检查时间

系统在以下时段自动检查（每 30 分钟）：
- **日盘**：9:00-11:30, 13:30-15:00
- **夜盘**：21:00-23:00

非交易时段和非交易日会自动跳过。

## 测试功能

运行测试脚本验证价格获取：
```bash
cd ~/projects/quant_factors
~/projects/quant_factors/quantenv/bin/python scripts/test_price_alert.py
```

## 故障排查

### 问题 1：告警未触发
- 检查 `active` 是否为 `true`
- 检查 `target_price` 是否合理
- 查看日志：`journalctl --user -u workflow-engine -f`

### 问题 2：价格获取失败
- 运行测试脚本检查数据源
- 确认品种代码正确
- 检查网络连接

### 问题 3：重复触发
- 检查 `max_triggers` 设置
- 查看状态文件确认触发次数
- 确认 `auto_reset` 设置

## 文件位置

| 文件 | 路径 |
|------|------|
| 配置文件 | `~/projects/quant_factors/config/price_alerts.yaml` |
| 状态文件 | `~/projects/quant_factors/data/price_alert_state.json` |
| 核心代码 | `~/projects/quant_factors/core/market_alert.py` |
| 测试脚本 | `~/projects/quant_factors/scripts/test_price_alert.py` |

## 注意事项

1. **一次性告警**：触发后自动禁用，避免重复骚扰
2. **手动重置**：需编辑配置文件重新启用
3. **价格波动**：触及目标价后可能继续波动，只触发一次
4. **数据源限制**：股票价格使用 akshare 接口，可能存在延迟

---

**版本**：v1.0  
**实现日期**：2026-07-22
