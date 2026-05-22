# Quant Factors 架构狠审任务表（2026-05-23）

> 本文档替换旧版架构/金融任务清单。  
> 旧 A/B 系列任务已基本完成；本文只记录 **重新审查后仍然值得继续改的真实架构问题**。  
> 原则：不为了“看起来工程化”而拆文件，只处理会影响一致性、可回测性、可维护性、数据口径可信度的问题。

---

## 当前状态快照

审查时间：2026-05-23 00:33 左右

验证结果：

```text
python -m unittest discover -s tests -q
Ran 158 tests ... OK

python scripts/audit_chains.py
chains=53 factor_modules=32 errors=0 warnings=1 metadata_diffs=0 known_missing_deps=1 unexpected_missing_deps=0
```

唯一已知 warning：

```text
pig_chicken_spread: known missing data_deps files: ['chicken_spot']
```

这是预期内缺口：`chicken_spot` 尚未找到稳定公开 API，不解析 HTML，不以白条鸡批发价冒充白羽肉鸡棚前价。

---

# 总体评价

当前项目已经从“脚本型量化系统”升级成“小型因子平台”：

- `FactorRunner` 已成为主要执行入口。
- `ChainDefinition` 已统一 `chains.yaml` 与 registry 元信息。
- `DataBus` 已集中加载和显式价格列语义。
- `SignalAggregator` 已有透明输出、冲突度、driver 去重。
- `report_formatter` 已抽出 API/推送共用格式。
- `trigger_backtest`、`ICMonitor`、`DATA_CONTRACT_SPEC` 已补齐统计评估和数据口径文档。
- 158 个测试通过，全链审计 0 errors。

但重新审查后，仍有 4 个核心架构问题值得继续处理。

---

# P0 — 必须优先处理

## P0-1. 统一 `/factor`、`/signal`、`/analyze` 的执行链路

### 问题

当前三个 API 入口执行路径不一致：

| API | 当前路径 | 问题 |
|-----|----------|------|
| `/analyze/<chain>` | `FactorRunner.run_chain()` | 标准路径 |
| `/factor/<chain>` | route 内直接 `factor.calculate()` | 绕过 `normalize_factor_data()`、IC snapshot、统一错误处理 |
| `/signal/<chain>` | route 内直接 `factor.signal()` | 没有先标准 calculate/cache，日志里 `factor_data=None` |

相关位置：

- `server.py` `/analyze/<chain>`：标准路径
- `server.py` `/factor/<chain_name>`：手写 calculate
- `server.py` `/signal/<chain_name>`：手写 signal
- `core/factor_runner.py`：标准执行链

### 风险

- 同一个因子从不同 API 路径跑出来可能语义不一致。
- `/factor` 返回的数据可能没有补齐 `factor_value/factor_value_type`。
- `/signal` 记录的信号缺少完整 `factor_data_json`。
- route 层仍然持有业务执行细节。

### 目标

所有外部 API 都走统一 runner/service，不在 route 里直接调用因子的 `calculate()` / `signal()`。

### 建议实现

在 `FactorRunner` 增加两个显式方法：

```python
def calculate_only(self, chain_name: str) -> dict:
    ...  # instantiate → calculate → normalize_factor_data


def signal_only(self, chain_name: str) -> dict:
    ...  # calculate_only → set _cached_data → signal → log
```

然后修改：

- `/factor/<chain_name>` 调用 `_runner.calculate_only(chain_name)`
- `/signal/<chain_name>` 调用 `_runner.signal_only(chain_name)`
- `/analyze/<chain>` 保持 `_runner.run_chain(chain)`

### 验收标准

- route 层不再直接调用 `factor.calculate()` / `factor.signal()`。
- `/factor` 返回的 `factor_data` 必须经过 `normalize_factor_data()`。
- `/signal` 记录日志时必须包含 `factor_data_json`。
- 新增/更新测试覆盖三个 API 的一致性。

---

## P0-2. `factor_value` 从 fallback 猜字段升级为显式契约

### 问题

当前 `core/factor_runner.py` 仍然维护大列表：

```python
FACTOR_VALUE_KEYS = [...]
```

执行时如果因子没有显式 `factor_value`，系统会尝试从 `zscore/ratio/spread/current/...` 等字段猜。

### 风险

- IC / hit-rate 可能取到展示字段，而非核心统计因子值。
- 新因子字段命名变化时，可能悄悄取错值。
- fallback key 列表会持续膨胀，形成隐性事实来源。

### 目标

所有用于评估的因子必须显式声明：

```python
{
  "factor_value": 1.23,
  "factor_value_type": "zscore | ratio | return | yoy | spread | percentile | score | raw_value",
  "factor_direction": "higher_better | lower_better | two_sided | regime",
  "horizon_days": 5,
}
```

fallback 只作为短期兼容机制，不能作为长期默认。

### 建议实现

第一步：审计增强

- `normalize_factor_data()` 如果 fallback 命中，给结果加：

```python
"factor_value_source": "fallback:<key>"
```

- 如果显式存在：

```python
"factor_value_source": "explicit"
```

第二步：`audit_chains.py` 将 fallback 命中列为 warning。

第三步：逐个因子补显式 `factor_value` 和语义字段。

最终：将 fallback warning 升级为 error。

### 验收标准

- 审计报告能列出所有 fallback 因子。
- 新增测试：fallback 会产生 warning/source 标记。
- 关键链条因子显式 `factor_value` 覆盖率达到 100%。
- 后续新增因子若没有 `factor_value`，测试失败。

---

# P1 — 高价值改进

## P1-1. DataBus 显式价格列下沉到刷新文件层

### 问题

`DataBus` 运行时会补：

- `close_raw`
- `close_adj`
- `return_raw`
- `return_adj`

但当前很多 parquet 原始文件仍是 legacy schema，仅含 `date/close/...`。

审计现象：

```text
price_schema ... legacy_close=21 explicit_price_columns=0
```

也就是说，显式价格列目前主要是 **运行时 schema**，不是 **文件层 schema**。

### 风险

- 如果有人绕过 DataBus 直接读 parquet，会拿到旧口径。
- 文件数据口径和运行时口径不一致。
- 数据刷新、回测、外部脚本之间容易产生隐性差异。

### 目标

刷新流程写出的 parquet 就包含显式列。

### 建议实现

新增公共函数，例如：

```python
def normalize_price_frame(df, dataset_name):
    ...
```

职责：

- 若是价格数据，写入 `close_raw/close_adj/return_raw/return_adj`。
- 国内主力连续品种应用换月调整。
- 非期货价格数据 `raw == adj`。
- 写入 metadata 或 sidecar manifest。

然后让：

- `download_history.py`
- `core/data_refresh.py`
- `DataBus.get()`

共享同一套标准化函数。

### 验收标准

- 刷新后 parquet 文件物理包含显式价格列。
- `scripts/audit_chains.py` 中 `explicit_price_columns > 0` 且 legacy 数量下降。
- `DataBus.get()` 对已显式列文件不重复/不冲突处理。
- 新增测试：刷新保存后的 parquet 直接读也包含显式列。

---

## P1-2. Driver 去重从硬编码规则表迁到配置，并预留统计相关性接口

### 问题

`SignalAggregator` 当前内置：

```python
DRIVER_PATTERNS = {
  "growth": ["pmi", "gdp", ...],
  "inflation": ["cpi", "ppi", ...],
  ...
}
```

这是可解释的第一版，但不是最终架构。

### 风险

- trigger 命名变动会影响 driver 分类。
- 业务配置被写死在代码中。
- 两个 driver 名义不同但历史高度相关时，无法自动折扣。
- 两个同 driver 信号也未必真的冗余。

### 目标

第一阶段：driver pattern 配置化。  
第二阶段：预留基于历史相关性的折扣接口。

### 建议实现

配置迁移到 `config/factor_params.yaml`：

```yaml
driver_patterns:
  growth:
    - pmi
    - gdp
    - industrial
  inflation:
    - cpi
    - ppi
    - oil_
```

`SignalAggregator` 启动时加载配置。

同时预留接口：

```python
def compute_signal_correlation_discount(signals, history):
    return discount_map
```

当前先返回规则折扣，未来替换成历史相关矩阵。

### 验收标准

- `SignalAggregator` 不再硬编码 driver pattern。
- 修改 config 后测试可验证 driver 分类变化。
- driver 分类/折扣出现在聚合结果里。
- 保留当前行为兼容。

---

# P2 — 中期优化

## P2-1. DataBus 单例改为可注入依赖，减少全局状态

### 问题

`DataBus` 当前是强单例：

```python
if existing data_dir != new data_dir:
    raise RuntimeError
```

因子内部：

```python
self._bus = DataBus(data_dir)
```

### 风险

- 测试必须频繁 `DataBus.reset()`。
- 多数据目录、多回测上下文不方便。
- 长进程服务内刷新数据后缓存一致性需要额外小心。

### 目标

保留默认单例便利性，但允许显式注入。

### 建议实现

`BaseFactor` 支持：

```python
def __init__(..., data_bus=None):
    self._bus = data_bus or DataBus(data_dir)
```

`FactorRunner` 创建因子时传入自身持有的 `_data_bus`。

### 验收标准

- 测试可用独立 DataBus 实例，不依赖全局 reset。
- 现有因子不改调用方式也能运行。
- `DataBus.reset()` 使用场景减少。

---

## P2-2. app 初始化封装成 `create_app()`

### 问题

`server.py` import 时直接创建全局对象：

- Flask app
- DataBus
- SignalLogger
- ICMonitor
- FactorRunner
- scheduler/push 初始化相关对象

### 风险

- import 副作用大。
- API 测试不易注入临时配置。
- 未来想 CLI 复用或多实例运行不方便。

### 目标

轻量 app factory，不做复杂多环境系统。

### 建议实现

```python
def create_app(settings=None):
    app = Flask(__name__)
    services = build_services(settings)
    register_routes(app, services)
    return app

app = create_app()
```

### 验收标准

- import `server` 不触发数据刷新/调度器副作用。
- 测试可以传入临时 data_dir/db_path。
- 现有启动命令兼容。

---

## P2-3. `download_history.py` 继续拆分数据源适配器

### 问题

`download_history.py` 约 485 行，包含：

- Tushare 国内期货
- AKShare 外盘
- FRED/EIA/央行数据
- 保存逻辑
- 数据缺口说明

### 风险

- 单文件过长，新增数据源容易继续堆积。
- 多个数据源错误处理风格不一致。
- API-only 原则容易被后来维护者破坏。

### 目标

拆成数据源 adapter，同时保留现有命令入口。

### 建议结构

```text
data_sources/
  domestic_futures.py
  foreign_futures.py
  macro_china.py
  macro_us.py
  eia.py
  known_missing.py
```

`download_history.py` 只做 orchestration。

### 验收标准

- 每个 adapter 可独立测试。
- 禁止 HTML scraping 的原则写进 known_missing / tests。
- 原有下载命令不变。

---

# 明确不建议现在做的事

以下不是当前瓶颈，不建议为了“架构好看”马上做：

1. 把 Flask route 拆成很多蓝图文件，但不改变执行语义。
2. 引入复杂 DI 框架。
3. 引入消息队列/任务队列。
4. 把个人项目强行改成多环境企业工程。
5. 在没有历史统计证据时继续拍脑袋改交易规则。

---

# 推荐执行顺序

## 第一批：执行一致性

1. P0-1：统一 `/factor`、`/signal`、`/analyze` 执行链路
2. P0-2：factor_value 显式契约 + fallback warning

## 第二批：数据口径下沉

3. P1-1：DataBus 显式价格列落盘

## 第三批：聚合配置化

4. P1-2：driver pattern 迁移到 config

## 第四批：长期维护

5. P2-1：DataBus 可注入
6. P2-2：create_app
7. P2-3：download_history 数据源 adapter 拆分

---

# 当前任务总览

| 优先级 | 编号 | 任务 | 状态 |
|--------|------|------|------|
| P0 | P0-1 | 统一 API 执行链路 | TODO |
| P0 | P0-2 | factor_value 显式契约 | TODO |
| P1 | P1-1 | 显式价格列下沉到 parquet | TODO |
| P1 | P1-2 | driver pattern 配置化 + 相关性接口 | TODO |
| P2 | P2-1 | DataBus 可注入依赖 | TODO |
| P2 | P2-2 | create_app app factory | TODO |
| P2 | P2-3 | download_history adapter 拆分 | TODO |

---

# 验收总标准

每完成一项任务必须：

1. 新增或更新测试。
2. 跑完整回归：

```bash
quantenv/bin/python3 -m unittest discover -s tests -q
```

3. 跑链条审计：

```bash
quantenv/bin/python3 scripts/audit_chains.py
```

4. commit 说明必须写清楚：
   - 改了什么
   - 为什么改
   - 验证结果
   - 向后兼容性

---

# 最终评价

这个项目当前最大问题不是“代码乱”，而是：

> **几个关键事实来源还没有完全统一。**

具体就是：

- API 执行事实来源还没完全统一到 `FactorRunner`。
- 因子评估值事实来源还没完全统一到显式 `factor_value`。
- 价格口径事实来源还没完全统一到 parquet 文件层。
- driver 分类事实来源还没完全统一到 config/统计数据。

把这四件事处理完，项目架构会明显再上一个台阶。
