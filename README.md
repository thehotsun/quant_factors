# quant_factors - 多因子量化分析系统

基于 AKShare 数据源，实现**农业产业链（肉蛋粮）、能源、金属、宏观、技术**五大体系的因子计算与信号生成，提供 Flask HTTP API 供工作流引擎调用。

## 架构概览

```
quant_factors/
├── core/                    # 核心框架
│   ├── data_bus.py          #   单例数据中心：统一加载+缓存，避免重复 I/O
│   ├── factor_registry.py   #   装饰器自动注册：告别手动维护 __init__.py
│   ├── signal_aggregator.py #   多因子信号融合：加权/投票/最强信号 + 相关性去重
│   └── signal_logger.py     #   信号落库：SQLite 记录每次信号，支持回溯复盘
├── factors/
│   ├── base.py              #   因子基类（DataBus/自适应阈值/自适应Z-score/连续信号/多窗口特征）
│   ├── meat/                #   肉类：猪肉 (1因子)
│   ├── feed/                #   饲料：豆粕/玉米/大豆/菜粕 (4因子)
│   ├── cross/               #   跨品种联动 (10因子)
│   │   ├── pig_grain_ratio.py      #   猪粮比 → 收储预期
│   │   ├── feed_cost.py            #   饲料成本指数 → 养殖利润
│   │   ├── crush_margin.py         #   大豆压榨利润 → 豆粕供应
│   │   ├── pig_chicken_spread.py   #   猪鸡价差 → 替代效应
│   │   ├── egg_feed_ratio.py       #   蛋料比 → 养殖利润
│   │   ├── copper_gold_ratio.py    #   铜金比 → 风险偏好（跨体系）
│   │   ├── oil_gold_link.py        #   原油→通胀→黄金（跨体系）
│   │   ├── forex_commodity.py      #   汇率→进口商品成本（跨体系）
│   │   ├── pmi_metals.py           #   PMI→工业金属需求（跨体系）
│   │   └── iron_rebar_cost.py      #   铁矿石→螺纹钢成本传导（跨体系）
│   ├── macro/               #   宏观：CPI/PMI/汇率/M2/社融/VIX/CBOT大豆 (8因子)
│   ├── energy/              #   能源：原油/天然气/油气比/石油股 (4因子)
│   ├── metals/              #   金属：铜/铝/螺纹钢/黄金/白银/铁矿石 (6因子)
│   └── technical/           #   技术：动量/波动率/期限结构/季节性 (4类，16条链)
├── evaluation/              # 因子评估
│   ├── evaluator.py         #   IC/IR/分层回测/夏普/最大回撤
│   └── ic_monitor.py        #   IC 衰减监控：跟踪因子预测能力变化
├── config/
│   ├── chains.yaml          #   链条配置（因子→资产→数据依赖）
│   └── factor_params.yaml   #   因子参数（可热更新）
├── server.py                # Flask API 服务（含内置定时任务：数据刷新 + IC 计算）
├── download_history.py      # 历史数据一次性下载
├── setup.sh                 # 一键部署脚本
├── start.sh                 # 后台启动脚本
└── requirements.txt         # Python 依赖
```

**共计 37 个因子类（53 条分析链）**，覆盖 5 大体系 + 跨体系联动，全部通过 `@FactorRegistry.register` 装饰器自动注册。

> **开发指南**：新增因子/体系的约束和步骤见 [AGENTS.md](AGENTS.md)。

## 核心设计

### 因子基类能力

每个因子继承 `BaseFactor` 后自动获得：

| 能力 | 说明 |
|------|------|
| **DataBus 统一加载** | `self.load(name)` 从缓存/本地 parquet 加载数据，所有因子共享，避免重复 I/O |
| **自适应阈值** | `self._adaptive_threshold()` 基于滚动波动率动态校准触发阈值，波动大时自动放宽 |
| **自适应 Z-score** | `self._adaptive_zscore_threshold()` 基于滚动窗口动态计算 Z-score 阈值，替代固定 ±2σ |
| **连续信号强度** | `self._continuous_signal()` 输出 -1.0（强卖）~ +1.0（强买），替代二元 BUY/SELL |
| **多窗口特征** | `self._multi_window_features()` 自动计算 5/10/20/60 日均线、波动率等 |
| **自动注册** | `@FactorRegistry.register()` 装饰器声明后自动加入全局注册表 |

### 信号聚合

`SignalAggregator` 支持三种聚合模式：

- **weighted**（默认）：按置信度加权融合
- **voting**：少数服从多数投票
- **strongest**：取信号强度最大的

同时内置**相关性去重**：自动检测高相关因子组（如动量因子不同窗口），每组只保留信号最强的，避免同类因子重复计数。

### 信号落库 & IC 监控

每次因子计算自动完成两件事：

| 能力 | 存储 | 用途 |
|------|------|------|
| **信号落库** | `data/signals.db` | 回溯历史信号，复盘买卖点准确率 |
| **因子快照** | `data/ic_monitor.db` | 计算 Rank IC，跟踪因子预测能力衰减 |

无需额外配置，服务运行即自动记录。

## 系统要求

- Python 3.10+
- WSL / Linux 环境（推荐）
- 网络连接（首次下载数据）

## 快速开始

### 1. 安装依赖

```bash
cd ~/projects/quant_factors
python3 -m venv quantenv
source quantenv/bin/activate
pip install -r requirements.txt
```

### 2. 下载历史数据（一次性）

```bash
python download_history.py
```

运行完成后，`data/` 目录下会生成以下 Parquet 文件：

| 分类 | 文件名 | 说明 |
|------|--------|------|
| 肉类 | `pork_futures.parquet` | 生猪期货(LH) |
| | `pork_futures_far.parquet` | 生猪远月期货 |
| | `egg_futures.parquet` | 鸡蛋期货(JD) |
| | `chicken_spot.parquet` | 白羽肉鸡现货 |
| 饲料 | `soybean_meal_futures.parquet` | 豆粕期货(M) |
| | `corn_futures.parquet` | 玉米期货(C) |
| | `soybean_domestic_futures.parquet` | 国产大豆(A) |
| | `soybean_import_futures.parquet` | 进口大豆(B) |
| | `rapeseed_meal_futures.parquet` | 菜粕期货(RM) |
| | `soybean_oil_futures.parquet` | 豆油期货(Y) |
| 能源 | `crude_oil_futures.parquet` | 原油期货(SC) |
| | `brent_oil.parquet` | 布伦特原油 |
| | `natural_gas_futures.parquet` | 天然气期货(NG) |
| | `eia_crude_stock.parquet` | EIA原油库存 |
| 金属 | `copper_futures.parquet` | 铜期货(CU) |
| | `aluminum_futures.parquet` | 铝期货(AL) |
| | `rebar_futures.parquet` | 螺纹钢期货(RB) |
| | `gold_futures.parquet` | 黄金期货(AU) |
| | `silver_futures.parquet` | 白银期货(AG) |
| | `iron_ore_futures.parquet` | 铁矿石期货(I) |
| | `thermal_coal_futures.parquet` | 动力煤期货(ZC) |
| 宏观 | `us_cpi.parquet` | 美国CPI |
| | `pmi.parquet` | 中国PMI |
| | `cpi.parquet` | 中国CPI |
| | `m2.parquet` | M2货币供应量 |
| | `usd_cny.parquet` | 美元/人民币汇率 |
| | `cbot_soybean.parquet` | CBOT大豆 |
| | `tips_yield.parquet` | 美国TIPS收益率(实际利率) |
| | `social_financing.parquet` | 社融规模增量 |
| | `vix.parquet` | VIX恐慌指数 |

### 3. 启动服务

```bash
# 前台运行
python server.py

# 后台运行
./start.sh
```

服务监听 `http://localhost:5001`

### 4. API 路由

#### 健康检查

```bash
curl http://localhost:5001/health
```

#### 单因子分析

```bash
# 农业产业链
curl http://localhost:5001/analyze/pork_etf        # 生猪→养殖ETF
curl http://localhost:5001/analyze/soybean_meal     # 豆粕
curl http://localhost:5001/analyze/corn             # 玉米
curl http://localhost:5001/analyze/soybean          # 大豆
curl http://localhost:5001/analyze/rapeseed_meal    # 菜粕

# 跨品种联动
curl http://localhost:5001/analyze/pig_grain_ratio   # 猪粮比
curl http://localhost:5001/analyze/feed_cost         # 饲料成本指数
curl http://localhost:5001/analyze/crush_margin      # 压榨利润
curl http://localhost:5001/analyze/pig_chicken_spread # 猪鸡替代
curl http://localhost:5001/analyze/egg_feed_ratio    # 蛋料比

# 跨体系联动
curl http://localhost:5001/analyze/copper_gold_ratio  # 铜金比→风险偏好
curl http://localhost:5001/analyze/oil_gold_link      # 原油→通胀→黄金
curl http://localhost:5001/analyze/forex_commodity    # 汇率→进口商品成本
curl http://localhost:5001/analyze/pmi_metals         # PMI→工业金属需求
curl http://localhost:5001/analyze/iron_rebar_cost    # 铁矿石→螺纹钢成本传导

# 宏观
curl http://localhost:5001/analyze/cpi              # 中国CPI
curl http://localhost:5001/analyze/cpi_gold         # 美国CPI→黄金
curl http://localhost:5001/analyze/pmi              # PMI
curl http://localhost:5001/analyze/forex            # 汇率
curl http://localhost:5001/analyze/money_supply     # M2
curl http://localhost:5001/analyze/social_financing # 社融
curl http://localhost:5001/analyze/cbot_soybean     # CBOT大豆
curl http://localhost:5001/analyze/vix              # VIX恐慌指数

# 能源
curl http://localhost:5001/analyze/crude_oil        # 原油
curl http://localhost:5001/analyze/natural_gas      # 天然气
curl http://localhost:5001/analyze/oil_gas_ratio    # 油气比
curl http://localhost:5001/analyze/oil_assets       # 布伦特原油→中国石油

# 金属
curl http://localhost:5001/analyze/copper           # 铜
curl http://localhost:5001/analyze/aluminum         # 铝
curl http://localhost:5001/analyze/rebar            # 螺纹钢
curl http://localhost:5001/analyze/gold             # 黄金
curl http://localhost:5001/analyze/silver           # 白银
curl http://localhost:5001/analyze/iron_ore         # 铁矿石

# 技术因子
curl http://localhost:5001/analyze/momentum          # 生猪动量
curl http://localhost:5001/analyze/momentum_copper   # 铜动量
curl http://localhost:5001/analyze/momentum_crude    # 原油动量
curl http://localhost:5001/analyze/momentum_gold     # 黄金动量
curl http://localhost:5001/analyze/momentum_rebar    # 螺纹钢动量
curl http://localhost:5001/analyze/volatility        # 生猪波动率
curl http://localhost:5001/analyze/volatility_copper # 铜波动率
curl http://localhost:5001/analyze/volatility_crude  # 原油波动率
curl http://localhost:5001/analyze/volatility_gold   # 黄金波动率
curl http://localhost:5001/analyze/volatility_rebar  # 螺纹钢波动率
curl http://localhost:5001/analyze/term_structure    # 期限结构
curl http://localhost:5001/analyze/seasonality       # 生猪季节性
curl http://localhost:5001/analyze/seasonality_copper # 铜季节性
curl http://localhost:5001/analyze/seasonality_crude  # 原油季节性
curl http://localhost:5001/analyze/seasonality_gold   # 黄金季节性
curl http://localhost:5001/analyze/seasonality_rebar  # 螺纹钢季节性
```

#### 综合链路分析（多因子聚合）

```bash
curl http://localhost:5001/analyze/full_meat_chain  # 肉蛋粮全产业链
curl http://localhost:5001/analyze/energy          # 能源体系
curl http://localhost:5001/analyze/metals          # 金属体系
curl http://localhost:5001/analyze/macro           # 宏观体系
```

#### 因子注册表

```bash
curl http://localhost:5001/registry                 # 查看所有已注册因子
```

#### 仅获取信号

```bash
curl http://localhost:5001/signal/pork_etf           # 只返回信号，不含因子数据
```

#### 链条列表

```bash
curl http://localhost:5001/chains                    # 查看所有可用链条
```

#### 因子原始数据

```bash
curl http://localhost:5001/factor/pork_etf           # 只返回因子计算数据，不含信号
```

### 5. 信号回溯与复盘

每次 API 调用产生信号时，自动写入 SQLite（`data/signals.db`），无需额外配置。

```bash
# 查看最近 30 天所有信号
curl http://localhost:5001/signals/history

# 只看某个因子的信号
curl "http://localhost:5001/signals/history?factor=pig_grain_ratio&days=90"

# 信号统计（买卖分布、各因子信号数）
curl http://localhost:5001/signals/stats
```

### 6. IC 衰减监控

服务启动后，每天 18:30 自动计算所有因子的 IC（Rank IC，即 Spearman 相关系数），跟踪因子预测能力变化。

```bash
# 查看单个因子的 IC 和衰减状态
curl http://localhost:5001/ic/pig_grain_ratio

# 全因子健康报告（一眼看出哪些因子在失效）
curl http://localhost:5001/ic/health
```

返回示例：

```json
{
  "summary": {
    "total": 15,
    "healthy": 10,
    "warning": 3,
    "decayed": 2
  },
  "decayed_factors": ["money_supply"]
}
```

- **healthy**：IC 稳定，因子有效
- **warning**：IC 轻微下降，需关注
- **decayed**：IC 大幅衰减，建议排查或停用

### 7. 定时任务（内置，无需 crontab）

服务启动时自动注册两个定时任务（在 `server.py` 中），**不需要额外配置 crontab**：

| 时间 | 任务 | 说明 |
|------|------|------|
| 每天 18:00 | 数据刷新 | 从 AKShare 拉取最新行情，覆盖 parquet 文件 |
| 每天 18:30 | IC 计算 | 计算所有因子的 Rank IC，写入 ic_monitor.db |

依赖 `apscheduler` 库（已在 requirements.txt 中）。如果未安装，定时任务静默跳过，不影响 API 服务。

### 8. 与 Node.js 工作流集成

```javascript
async function checkSignal(chain) {
    const res = await fetch(`http://localhost:5001/analyze/${chain}`);
    const data = await res.json();
    if (data.opportunity) {
        const dir = data.opportunity.direction === 'BUY' ? '买入' : '卖出';
        const strength = data.signal_strength != null
            ? ` (强度: ${(data.signal_strength * 100).toFixed(0)}%)`
            : '';
        console.log(`[${chain}] ${dir} ${data.opportunity.asset}${strength}: ${data.opportunity.reason}`);
    }
}

// 定时轮询
setInterval(() => {
    checkSignal('pork_etf');
    checkSignal('pig_grain_ratio');
    checkSignal('feed_cost');
}, 300000);
```

## 常见问题

### Q: 数据文件损坏怎么办？

重新运行 `python download_history.py` 即可。

### Q: 如何调整因子触发阈值？

编辑 `config/factor_params.yaml`，修改对应因子的 `params`，重启服务生效。

### Q: 如何查看某个因子的详细计算数据？

```bash
curl http://localhost:5001/factor/pig_grain_ratio
```

### Q: 如何判断一个因子是否还有效？

```bash
# 查看 IC 健康报告
curl http://localhost:5001/ic/health

# 查看单个因子的 IC 和衰减趋势
curl http://localhost:5001/ic/pig_grain_ratio
```

IC 绝对值 > 0.05 表示有效，0.02~0.05 需关注，< 0.02 建议排查。

### Q: 信号历史存在哪里？怎么回溯？

所有信号自动写入 `data/signals.db`（SQLite），可通过 API 查询：

```bash
curl "http://localhost:5001/signals/history?factor=pork_etf&days=90"
```

也可以用任何 SQLite 客户端直接打开 `data/signals.db` 查看。

### Q: 定时任务没执行怎么办？

检查日志中是否有 `APScheduler 已启动` 字样。如果没有，执行 `pip install apscheduler` 后重启服务。

### Q: 技术因子（动量/波动率等）如何使用？

技术因子需要传入 `symbol` 参数，通过 API 调用时在 chains.yaml 中配置对应的 `factor_module` 和 `factor_class`，或直接在代码中实例化：

```python
from factors.technical import MomentumFactor
factor = MomentumFactor(symbol="pork_futures")
data = factor.calculate()  # 返回 momentum_5d/20d/60d/acceleration/score
```