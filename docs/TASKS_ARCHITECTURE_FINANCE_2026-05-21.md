# Quant Factors 后续任务清单（代码架构 / 金融逻辑）

日期：2026-05-21

## 总原则

- 这是个人项目，不做过度工程化的生产/测试/预发环境拆分。
- 优先解决代码架构问题，再处理金融逻辑校准。
- 代码优先级核心：依赖清晰、事实来源唯一、上下游边界明确、减少重复维护。
- 金融逻辑改动必须尽量先有统计验证，不凭感觉直接改阈值、方向、持仓天数。

---

# A. 代码架构任务

## A0. 当前最优先任务

### A0-1. 消除因子导入重复维护

**问题**

当前因子需要同时维护多处：

- `factors/**/*.py` 里的因子类和 `@FactorRegistry.register`
- `config/chains.yaml`
- `core/factor_runner.py` 里的 `FACTOR_IMPORTS`
- README / AGENTS 文档

这会导致新增或移动因子时容易漏改。

**目标**

让 `chains.yaml` 或 `FactorRegistry` 成为唯一事实来源，至少先去掉 `FACTOR_IMPORTS` 手写列表。

**建议实现**

第一阶段：

- 从 `chains.yaml` 自动读取所有 `factor_module`
- `FactorRunner.ensure_imported()` 自动 import 这些 module
- 删除或弃用 `FACTOR_IMPORTS`

第二阶段：

- 遍历 `factors/**/*.py` 自动发现模块
- import 后由 `FactorRegistry` 统一收集注册信息
- `chains.yaml` 只描述链条组合、参数、symbol、far_symbol

**验收标准**

- 新增一个普通因子时，不需要再改 `FACTOR_IMPORTS`
- `/registry` 和 `/chains` 数量一致或差异可解释
- 增加测试：所有 `chains.yaml` 中的非 composite chain 都能成功 import + instantiate

---

### A0-2. 统一链条配置、注册表、执行器之间的依赖关系

**问题**

现在存在三层概念：

- `FactorRegistry`：因子注册元信息
- `chains.yaml`：API 链条配置
- `FactorRunner`：执行时实例化和运行

三者边界还不清楚。比如 registry 有 description/asset/data_deps，chains.yaml 也有类似字段。

**目标**

明确职责：

- `FactorRegistry`：因子本身的静态元数据
- `chains.yaml`：运行配置、组合链、参数覆盖
- `FactorRunner`：只负责执行，不保存业务事实

**建议实现**

- 写一个 `core/chain_config.py`
- 启动时构建统一 `ChainDefinition`
- 合并 registry metadata + yaml runtime config
- 对重复字段做一致性检查

**验收标准**

- 若 `chains.yaml` 与 registry 的 `asset/data_deps/category` 不一致，启动或测试能提示
- `FactorRunner` 不再关心 description/category 等展示字段

---

### A0-3. 建立全链条 schema 检查脚本

**问题**

现在只有少数优先修复测试，不能系统检查 53 条链。

**目标**

新增一个检查工具，直接输出每条链是否满足最低标准。

**建议文件**

- `scripts/audit_chains.py`
- 或 `tests/test_chain_integrity.py`

**检查内容**

每个非 composite chain：

- 能 import
- 能 instantiate
- `calculate()` 不抛异常
- 返回 dict
- 有 `factor_value` 或可解释的缺失原因
- `signal()` 返回 None 或稳定 signal schema
- data_deps 文件存在或明确缺失

每个 composite chain：

- sub_chains 都存在
- 子链不循环依赖
- 聚合结果 schema 稳定

**验收标准**

- 一条命令可以看到所有链的问题清单
- 后续改因子前后都可以跑这个检查

---

## A1. 高优先级代码任务

### A1-1. 拆分 `server.py` 中剩余业务逻辑

**问题**

`server.py` 仍然包含：

- composite chain 执行
- daily IC compute
- daily push
- push endpoint 业务逻辑
- scheduler 初始化

**目标**

让 `server.py` 只保留 Flask route 和很薄的调用。

**建议拆分**

```text
core/composite_runner.py
core/ic_service.py
core/push_service.py
```

不需要复杂 create_app 环境切分；个人项目可以保持简单，但不要让 route 文件承担业务逻辑。

**验收标准**

- `_run_composite_chain` 从 `server.py` 移出
- `_daily_ic_compute` 从 `server.py` 移出
- `_daily_push` 从 `server.py` 移出
- route 函数基本只做参数解析和 jsonify

---

### A1-2. 明确 `factor_value` 语义，减少 fallback 猜字段

**问题**

`FactorRunner.extract_factor_value()` 当前靠字段列表猜因子值。

**风险**

IC 计算可能使用了展示字段，而不是适合统计评估的因子值。

**目标**

每个因子主动声明自己的核心因子值。

**建议 schema**

```python
{
    "factor_value": 1.23,
    "factor_value_type": "zscore | ratio | return | yoy | spread | percentile | score",
    "factor_direction": "higher_better | lower_better | two_sided | regime",
    "target_asset": "...",
    "horizon_days": 5,
}
```

**验收标准**

- 新增测试：所有用于 IC 的因子必须有 `factor_value`
- fallback 只作为兼容警告，不作为长期默认

---

### A1-3. SignalLogger 保存完整信号上下文

**问题**

当前信号表缺少 trigger、holding_days、stop_loss、完整 signal json、run_id 等字段。

**目标**

让每次信号都可以完整复盘。

**建议新增字段**

- `trigger`
- `holding_days`
- `stop_loss`
- `signal_json`
- `factor_data_json`
- `run_id`
- `chain_name`
- `as_of`
- `available_date`

**验收标准**

- 从数据库能还原某次推送的全部原始 signal
- composite chain 的子信号能通过同一个 `run_id` 串起来

---

### A1-4. 数据刷新写入改成原子写

**问题**

数据刷新如果直接覆盖 parquet，网络或接口异常时可能污染已有好数据。

**目标**

数据写入流程变成：

```text
fetch → validate → write tmp → read back check → atomic replace → invalidate cache
```

**验收标准**

- 空 DataFrame 不覆盖旧文件
- 字段不满足最低要求不覆盖旧文件
- 写 parquet 中途失败不会破坏旧数据

---

### A1-5. DataBus 价格口径显式化

**问题**

`DataBus` 当前自动做换月跳空调整，并把结果写回 `close`，同时保留 `close_raw`。

**风险**

下游因子不知道自己用的是 raw price 还是 adjusted price。

**目标**

明确价格字段：

- `close_raw`
- `close_adj`
- `return_raw`
- `return_adj`
- 默认 `close` 的含义要文档化

**验收标准**

- 每个因子能明确使用哪个价格口径
- 技术类/回测收益类优先考虑 raw return
- 估值位置类可以使用 adjusted price

---

## A2. 中优先级代码任务

### A2-1. 聚合器输出更透明

**问题**

当前聚合结果只有 components，缺少冲突度、相关性折扣、driver 分组。

**建议**

聚合输出增加：

```python
{
    "driver_groups": {...},
    "conflict_score": ...,
    "dedup_applied": true,
    "raw_signal_count": ...,
    "effective_signal_count": ...,
}
```

---

### A2-2. 推送和 API 输出共用格式化层

**问题**

推送格式和 API 结果之间有重复解释逻辑。

**建议**

新增：

```text
core/report_formatter.py
```

统一负责：

- signal 展示
- percentile 展示
- position label
- direction summary

---

### A2-3. 配置加载集中化

**问题**

`server.py`、`FactorRunner`、`data_refresh`、push 各自读不同配置。

**建议**

新增：

```text
core/settings.py
```

统一管理：

- data_dir
- chains config
- factor params
- push config
- token/env 检查

---

# B. 金融逻辑任务

## B0. 当前最优先金融任务，但排在代码架构之后

### B0-1. 做 trigger 级回测

**问题**

现在系统能生成信号，但还不知道每个 trigger 是否真的有效。

**目标**

每个 trigger 输出最小统计：

- 触发次数
- 未来 1/5/10/20 日收益
- 胜率
- 平均收益
- 中位收益
- 最大亏损
- 分年度表现

**建议文件**

```text
evaluation/trigger_backtest.py
```

**验收标准**

- 能回答：哪个 trigger 有用，哪个 trigger 只是逻辑故事
- 后续改阈值前先看 trigger 统计

---

### B0-2. 统一 `signal_strength` 金融语义

**问题**

现在 `signal_strength` 混合了方向强度、统计偏离、风险状态、解释分数。

**目标**

拆成：

```python
factor_score          # 原始因子分
trade_signal_strength # 与 BUY/SELL 方向一致的交易强度
risk_modifier         # 只修正仓位，不表达方向
confidence            # 证据可信度
```

**验收标准**

- HOLD 类型因子不再贡献方向强度
- 均值回归类因子的 strength 与交易方向一致
- 聚合器只使用 `trade_signal_strength`

---

### B0-3. 所有宏观引用统一 as_of

**问题**

已知还有这些因子直接读取 PMI：

- `factors/cross/pmi_metals.py`
- `factors/metals/silver.py`
- `factors/metals/metals.py`

**目标**

所有宏观数据引用统一经过 `available_asof()`。

**验收标准**

- grep 不再出现 cross/metals 因子直接 `self.load("pmi")` 后立即使用
- 新增测试覆盖 cross 因子的宏观 as_of 过滤

---

## B1. 高优先级金融任务

### B1-1. 止损和持仓天数用波动率校准

**问题**

当前大量 signal 使用固定：

- `stop_loss=-0.02`
- `holding_days=5/10/20/30`

**目标**

按品种波动率校准风险。

**建议**

- 引入 ATR 或 realized volatility
- `stop_loss = -k * vol_20d * sqrt(holding_days)`
- 区分信号失效和交易止损

---

### B1-2. 商品期货主力连续口径校准

**问题**

当前自动换月跳空调整可能误判真实跳空，也可能影响动量/波动率。

**目标**

建立数据口径表，明确每个品种：

- 数据来源
- 是否主力连续
- 是否复权/换月调整
- 是否有夜盘
- 可交易时间
- contract code 是否保存

**建议文件**

```text
docs/DATA_CONTRACT_SPEC.md
```

---

### B1-3. 聚合器引入 driver 去重

**问题**

多个信号可能来自同一个宏观驱动，不能当成独立证据。

**建议 driver**

- `growth`
- `inflation`
- `real_rate`
- `fx`
- `risk_off`
- `inventory`
- `cost`
- `seasonality`
- `technical`

**验收标准**

- 同 driver 多信号触发时做折扣
- 跨 driver 信号一致时才提高置信度

---

### B1-4. 固定阈值改为分位 / z-score

**问题**

社融、M2、CPI、VIX、油价涨跌等固定阈值容易 regime drift。

**目标**

逐步从固定阈值迁移到：

- rolling percentile
- rolling z-score
- regime relative threshold

---

## B2. 中优先级金融任务

### B2-1. 宏观传导加入 regime filter

**问题**

当前很多传导是线性的：

- 油涨 → 黄金 BUY
- 人民币贬值 → 商品 BUY
- PMI 上行 → 铜 BUY
- 社融上行 → A股 BUY

**建议加入 regime**

- growth regime
- inflation regime
- liquidity regime
- dollar regime
- risk sentiment
- inventory regime

---

### B2-2. IC 评估按因子类型拆分

**问题**

时间序列单资产因子、宏观因子、截面因子不应该都用同一种 IC 解释。

**建议**

拆成：

- time-series IC
- trigger return stats
- direction hit rate
- cross-sectional IC

---

# C. 建议执行顺序

## 第一批：先解决依赖不清晰和重复维护

1. A0-1 消除 `FACTOR_IMPORTS` 手写列表
2. A0-2 统一 `chains.yaml` / `FactorRegistry` / `FactorRunner` 关系
3. A0-3 建立全链条 schema 检查脚本

## 第二批：继续瘦身服务层

4. A1-1 拆分 `server.py` 剩余业务逻辑
5. A1-3 SignalLogger 保存完整上下文
6. A1-4 数据刷新原子写

## 第三批：金融验证前置

7. B0-3 统一所有宏观 as_of
8. B0-1 trigger 级回测
9. B0-2 重定义 signal_strength 语义

## 第四批：金融参数校准

10. B1-1 波动率止损
11. B1-3 driver 去重
12. B1-4 阈值分位化

---

# D. 下一步建议立即做的具体代码任务

我建议下一步直接做这三个，风险低、收益高：

1. 从 `chains.yaml` 自动 import factor modules，废弃 `FACTOR_IMPORTS`。
2. 新增 `tests/test_chain_integrity.py`，检查所有链条能 import / instantiate。
3. 新增 `scripts/audit_chains.py`，输出链条、注册表、data_deps、schema 缺口报告。

这三个做完后，项目依赖关系会清楚很多，后面再拆 `server.py` 和改金融逻辑会稳得多。
