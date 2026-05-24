# 方案三：现货 + 期货 + 股票/ETF 混合信号链 — 任务清单

**最后更新**: 2026-05-24 09:50
**当前阶段**: Batch 2.5 完成（数据源适配器），Batch 3/4 待用户确认

---

## 当前状态基线

已完成：

1. `ChainDefinition` 支持 `trade_asset / trade_asset_type / execution_asset / signal_target / drivers`
2. `chains.yaml` 56 条链（含 3 条新混合链）全部使用新结构
3. `price_schema` 支持 `get_data_kind()` 区分 futures / spot / equity / macro
4. `DataBus` 元数据带 `data_kind` / `price_role`，支持 `get_price()` / `get_driver_bundle()` / `get_driver_status()`
5. 混合因子基类 `MixedDriverFactor` 已就绪
6. 3 条样板混合链：`pork_stock_signal` / `gold_etf_signal` / `oil_stock_signal`
7. 通用模板因子 `CommodityToEquitySignal`
8. 链条配置校验器 `scripts/validate_chain_schema.py`
9. 审计器支持 known_missing 分类
10. 全量 210 测试通过
11. 现货数据源适配器 `data_sources/spot.py` — fetch_pork_spot()
12. 股票/ETF 数据源适配器 `data_sources/equity.py` — fetch_etf_hist() + fetch_stock_hist()
13. download_history.py 编排新数据源（生猪现货 + 3 个股票/ETF）
14. KNOWN_MISSING_PRICE_DATA 精简至 chicken_spot

---

## 进度总览

| 批次 | 任务 | 状态 | commit |
|------|------|------|--------|
| Batch 1 | 架构层定型（任务 1-4） | ✅ 完成 | 585dadd |
| Batch 2 | DataBus + 因子基类 + 样板链 + 审计（任务 8-11, 13-14, 24-25） | ✅ 完成 | 99007ed |
| Batch 2.5 | 数据源适配器（任务 5-7） | ✅ 完成 | |
| Batch 3 | 回测层 + 信号层升级（任务 12, 15-20） | ⏸ 待确认 | |
| Batch 4 | 实际数据接入 + API + 推送（任务 21-23, 26-29） | ⏸ 待确认 | |

---

## 任务清单

### 阶段一：链条架构定型

- [x] **任务 1**: 统一 `chains.yaml` 新结构 — 56 条链全部迁移
- [x] **任务 2**: 扩展 `ChainDefinition` — 新增 trade_asset_type / execution_asset / signal_target
- [x] **任务 3**: 新增链条配置校验器 `scripts/validate_chain_schema.py`
- [x] **任务 4**: 完善 `DATASET_KINDS` — futures / spot / equity / macro / unknown

### 阶段二：数据源层升级

- [x] **任务 5**: 建立现货数据源适配器目录 `data_sources/spot.py` — fetch_pork_spot()
- [x] **任务 6**: 建立权益/ETF 数据源适配器 `data_sources/equity.py` — fetch_etf_hist() + fetch_stock_hist()
- [x] **任务 7**: 统一 `save_parquet()` 对不同数据类型的处理 — 已通过 _normalize_history_frame + normalize_price_frame 自动处理

### 阶段三：DataBus 强化

- [x] **任务 8**: `DataBus.get_price()` — 按用途读价格（raw/adjusted/return_raw/return_adj）
- [x] **任务 9**: `DataBus.get_driver_bundle()` — 按链条一次性取出所有驱动数据
- [x] **任务 10**: `DataBus.get_driver_status()` — 检查驱动数据可用性

### 阶段四：因子层迁移

- [x] **任务 11**: 定义混合因子基类 `factors/mixed/base.py` — MixedDriverFactor
- [ ] **任务 12**: 迁移 `pig_chicken_spread` 使用 MixedDriverFactor
- [x] **任务 13**: 新增 `pork_stock_signal` 混合链
- [x] **任务 14**: 新增 `commodity_to_equity_signal` 通用模板

### 阶段五：信号输出升级

- [ ] **任务 15**: 统一信号结构 — drivers / driver_data / trade_asset
- [ ] **任务 16**: 升级 FactorRunner — 注入 chain_def ✅（已做，向后兼容）
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

- [x] **任务 24**: 升级 `audit_chains.py` — 检查 drivers / trade_asset / known_missing
- [x] **任务 25**: 禁止现货假数据固化 — PRICE_DATA_NAMES / KNOWN_MISSING_PRICE_DATA

### 阶段九：补第一批可跑链条

- [ ] **任务 26**: 接入养殖 ETF 数据（159865）
- [ ] **任务 27**: `pork_stock_signal` 实际可跑（需 breeding_etf 数据）
- [ ] **任务 28**: `gold_etf_signal` 实际可跑（需 gold_etf 数据）
- [ ] **任务 29**: `oil_stock_signal` 实际可跑（需 petrochina_stock 数据）

### 阶段十：文档和回归

- [ ] **任务 30**: 更新 README — 解释新架构
- [ ] **任务 31**: 更新 DATA_CONTRACT_SPEC — 所有数据源口径
- [ ] **任务 32**: 全量测试回归

---

## 已完成的关键文件

| 文件 | 说明 |
|------|------|
| `core/chain_config.py` | ChainDefinition 新增 trade_asset / drivers 等字段 |
| `core/price_schema.py` | DATASET_KINDS / get_data_kind() / KNOWN_MISSING_PRICE_DATA |
| `core/data_bus.py` | get_price() / get_driver_bundle() / get_driver_status() |
| `core/factor_runner.py` | 向后兼容注入 chain_def |
| `factors/mixed/base.py` | MixedDriverFactor 基类 |
| `factors/mixed/pork_stock_signal.py` | 生猪→养殖ETF 混合信号因子 |
| `factors/mixed/commodity_to_equity.py` | 通用商品→股票模板因子 |
| `config/chains.yaml` | 56 条链，含 3 条新混合链 |
| `scripts/validate_chain_schema.py` | 链条配置校验器 |
| `scripts/audit_chains.py` | 审计器支持 known_missing |
| `data_sources/spot.py` | 现货数据源适配器（生猪现货） |
| `data_sources/equity.py` | 股票/ETF 数据源适配器 |
| `docs/MIXED_CHAIN_TASKLIST.md` | 本文档 |

---

## 明天新 Session 启动指南

1. 读此文档确认当前进度
2. 检查最新 commit：`git log --oneline -5`
3. 确认是否执行 Batch 3（回测层）/ Batch 4（数据源接入）
4. 如有新需求，更新此文档后执行
5. 所有任务以此文档为准

---

## 关键约束

1. **不解析 HTML** — 没有稳定接口的数据继续 known missing
2. **不冒充口径** — 不用白条鸡批发价冒充白羽肉鸡棚前价
3. **向后兼容** — 旧因子代码不受影响
4. **分批测试** — 每批跑全量测试后 commit
5. **文档为准** — 所有任务进度以此文档为准
