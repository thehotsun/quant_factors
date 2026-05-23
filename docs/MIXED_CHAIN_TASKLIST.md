# 方案三：现货 + 期货 + 股票/ETF 混合信号链 — 任务清单

**最后更新**: 2026-05-23 23:12
**当前阶段**: Batch 1 完成，Batch 2 执行中

---

## 当前状态基线

已完成：

1. `ChainDefinition` 支持 `trade_asset / trade_asset_type / execution_asset / signal_target / drivers`
2. `chains.yaml` 53 条链全部迁移至新结构
3. `price_schema` 支持 `get_data_kind()` 区分 futures / spot / equity / macro
4. `DataBus` 元数据带 `data_kind` 和 `price_role`
5. 链条配置校验器 `scripts/validate_chain_schema.py`
6. 全量 204 测试通过

---

## 进度总览

| 批次 | 任务 | 状态 | commit |
|------|------|------|--------|
| Batch 1 | 架构层定型（任务 1-3, 部分 4） | ✅ 完成 | 585dadd |
| Batch 2 | DataBus 扩展 + 混合因子基类 + 样板链（任务 8-14, 21, 23, 24） | 🔄 执行中 | |
| Batch 3 | 回测层 + 旧因子迁移（任务 15-20） | ⏸ 待确认 | |
| Batch 4 | ETF 数据源接入（任务 5-7, 26-29） | ⏸ 待确认 | |

---

## 任务清单

### 阶段一：链条架构定型

- [x] **任务 1**: 统一 `chains.yaml` 新结构 — 53 条链全部迁移
- [x] **任务 2**: 扩展 `ChainDefinition` — 新增 trade_asset_type / execution_asset / signal_target
- [x] **任务 3**: 新增链条配置校验器 `scripts/validate_chain_schema.py`
- [x] **任务 4**: 完善 `DATASET_KINDS` — futures / spot / equity / macro / unknown

### 阶段二：数据源层升级

- [ ] **任务 5**: 建立现货数据源适配器目录 `data_sources/spot/`
- [ ] **任务 6**: 建立权益/ETF 数据源适配器 `data_sources/equity.py`
- [ ] **任务 7**: 统一 `save_parquet()` 对不同数据类型的处理

### 阶段三：DataBus 强化

- [ ] **任务 8**: `DataBus.get_price()` — 按用途读价格（raw/adjusted/return_raw/return_adj）
- [ ] **任务 9**: `DataBus.get_driver_bundle()` — 按链条一次性取出所有驱动数据
- [ ] **任务 10**: 完善 metadata — is_tradeable / source / unit / currency

### 阶段四：因子层迁移

- [ ] **任务 11**: 定义混合因子基类 `factors/mixed/base.py` — MixedDriverFactor
- [ ] **任务 12**: 迁移 `pig_chicken_spread` 使用 MixedDriverFactor
- [ ] **任务 13**: 新增 `pork_stock_signal` 混合链
- [ ] **任务 14**: 新增 `commodity_to_equity_signal` 通用模板

### 阶段五：信号输出升级

- [ ] **任务 15**: 统一信号结构 — drivers / driver_data / trade_asset
- [ ] **任务 16**: 升级 FactorRunner — 注入 chain_def
- [ ] **任务 17**: 升级 SignalAggregator — driver_groups / driver_conflicts

### 阶段六：回测层升级

- [ ] **任务 18**: 回测支持"驱动数据 ≠ 交易标的"
- [ ] **任务 19**: IC 监控按 trade_asset 分组
- [ ] **任务 20**: 混合链回测测试

### 阶段七：API 和推送升级

- [ ] **任务 21**: API 返回 mixed chain 元信息（trade_asset / drivers / driver_health）
- [ ] **任务 22**: API 增加 driver health 状态
- [ ] **任务 23**: 推送格式升级 — 展示驱动和风险

### 阶段八：审计和安全

- [ ] **任务 24**: 升级 `audit_chains.py` — 检查 drivers / trade_asset / spot 口径
- [ ] **任务 25**: 禁止现货假数据冒充 — 文档 + 测试固化

### 阶段九：补第一批可跑链条

- [ ] **任务 26**: 接入养殖 ETF 数据（159865）
- [ ] **任务 27**: 新增 `pork_stock_signal` 链条
- [ ] **任务 28**: 新增 `gold_etf_signal` 链条
- [ ] **任务 29**: 新增 `oil_stock_signal` 链条

### 阶段十：文档和回归

- [ ] **任务 30**: 更新 README — 解释新架构
- [ ] **任务 31**: 更新 DATA_CONTRACT_SPEC — 所有数据源口径
- [ ] **任务 32**: 全量测试回归

---

## 执行策略

### 今晚执行（安全加法，不改旧逻辑）

**Batch 2**（当前执行）:
- 任务 8: DataBus.get_price()
- 任务 9: DataBus.get_driver_bundle()
- 任务 11: MixedDriverFactor 基类
- 任务 13: pork_stock_signal 样板链
- 任务 14: commodity_to_equity_signal 通用模板
- 任务 16: FactorRunner 向后兼容注入 chain_def
- 任务 21: API 返回 mixed chain 元信息
- 任务 23: 推送格式升级
- 任务 24: 审计器升级
- 任务 25: 禁止假数据固化
- 任务 30-32: 文档和回归

### 明天确认后执行

**Batch 3**（需确认回测逻辑）:
- 任务 15: 统一信号结构
- 任务 17: SignalAggregator 升级
- 任务 18-20: 回测层改造

**Batch 4**（需确认数据源/接口）:
- 任务 5-7: 数据源适配器
- 任务 26-29: ETF 数据实际下载和接入

---

## 关键约束

1. **不解析 HTML** — 没有稳定接口的数据继续 known missing
2. **不冒充口径** — 不用白条鸡批发价冒充白羽肉鸡棚前价
3. **向后兼容** — 旧因子代码不受影响
4. **分批测试** — 每批跑全量测试后 commit
5. **文档为准** — 所有任务进度以此文档为准

---

## 明天新 Session 启动指南

1. 读此文档确认当前进度
2. 检查最新 commit
3. 确认是否执行 Batch 3 / Batch 4
4. 如有新需求，更新此文档后执行
