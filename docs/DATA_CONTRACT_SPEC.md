# 数据口径规范 — DATA_CONTRACT_SPEC

日期：2026-05-22

本文档记录每个数据品种的来源、合约类型、换月调整、交易时间等关键信息，供因子开发和回测参考。

---

## 一、国内期货（Tushare 主力连续）

通过 `Tushare` 的 `fut_daily()` 接口获取主力合约日线数据。

| 品种 | 文件名 | Tushare ts_code | 交易所 | 夜盘 | 备注 |
|------|--------|-----------------|--------|------|------|
| 生猪 | `pork_futures` | LH.DCE | 大商所 | ❌ | 现金交割，无夜盘 |
| 鸡蛋 | `egg_futures` | JD.DCE | 大商所 | ❌ | |
| 豆粕 | `soybean_meal_futures` | M.DCE | 大商所 | ✅ 21:00-23:00 | |
| 玉米 | `corn_futures` | C.DCE | 大商所 | ❌ | |
| 国产大豆 | `soybean_domestic_futures` | A.DCE | 大商所 | ✅ 21:00-23:00 | |
| 进口大豆 | `soybean_import_futures` | B.DCE | 大商所 | ✅ 21:00-23:00 | |
| 菜粕 | `rapeseed_meal_futures` | RM.ZCE | 郑商所 | ✅ 21:00-23:30 | |
| 豆油 | `soybean_oil_futures` | Y.DCE | 大商所 | ✅ 21:00-23:00 | |
| 原油 | `crude_oil_futures` | SC.INE | 能源中心 | ✅ 21:00-次日02:30 | 人民币计价 |
| 铜 | `copper_futures` | CU.SHF | 上期所 | ✅ 21:00-次日01:00 | |
| 铝 | `aluminum_futures` | AL.SHF | 上期所 | ✅ 21:00-次日01:00 | |
| 螺纹钢 | `rebar_futures` | RB.SHF | 上期所 | ✅ 21:00-23:00 | |
| 黄金 | `gold_futures` | AU.SHF | 上期所 | ✅ 21:00-次日02:30 | |
| 白银 | `silver_futures` | AG.SHF | 上期所 | ✅ 21:00-次日02:30 | |
| 铁矿石 | `iron_ore_futures` | I.DCE | 大商所 | ✅ 21:00-23:00 | |
| 动力煤 | `thermal_coal_futures` | ZC.ZCE | 郑商所 | ✅ 21:00-23:30 | 政策限价，流动性差 |

**口径说明**：
- 数据类型：**主力连续合约**（Tushare 自动切换）
- 换月调整：Tushare 主力连续默认**不复权**，换月跳空由 `DataBus._adjust_roll_gap()` 在本地处理
- 价格单位：元/吨（除原油为元/桶）
- 数据频率：日线（OHLCV + 持仓量）
- 本地调整后字段：`close_raw`（原始）→ `close_adj`（跳空调整后）→ `close`（= close_adj）

---

## 二、生猪远月代理（AKShare 基差日表）

| 项目 | 值 |
|------|-----|
| 文件名 | `pork_futures_far` |
| 数据源 | AKShare `futures_spot_price_daily(vars_list=["LH"])` |
| 核心字段 | `dominant_contract_price`（主力合约结算价） |
| 合约代码 | 保存在 `contract` 字段（如 `lh2607`） |
| 附加字段 | `spot_price`（现货价）、`basis`（基差）、`basis_rate`（基差率） |
| 换月调整 | 无（每日取当日主力合约价，不做连续拼接） |
| 数据频率 | 日线 |
| 备注 | 用于 `term_structure` 因子，不是真正的远月连续合约 |

---

## 三、外盘期货

| 品种 | 文件名 | 数据源 | symbol | 备注 |
|------|--------|--------|--------|------|
| 布伦特原油 | `brent_oil` | FRED `DCOILBRENTEU` | — | USD/桶，日线 |
| 天然气 | `natural_gas_futures` | AKShare `futures_foreign_hist` | NG | USD/MMBtu |
| CBOT 大豆 | `cbot_soybean` | AKShare `futures_foreign_hist` | S | 美分/蒲式耳 |

**口径说明**：
- FRED 数据为日度观测值，非期货合约
- AKShare 外盘期货为连续合约，换月方式由 AKShare 内部处理
- 无夜盘概念（外盘几乎 23 小时交易）

---

## 四、宏观数据

| 品种 | 文件名 | 数据源 | 频率 | 发布延迟 | as_of 处理 |
|------|--------|--------|------|----------|-----------|
| 中国 CPI | `cpi` | AKShare `macro_china_cpi` | 月度 | ~10 个工作日 | ✅ `available_asof` |
| 中国 PMI | `pmi` | AKShare `macro_china_pmi` | 月度 | ~1 个工作日 | ✅ `available_asof` |
| 中国 M2 | `m2` | AKShare `macro_china_money_supply` | 月度 | ~12 个工作日 | ✅ `available_asof` |
| 社融 | `social_financing` | 央行官网 + AKShare | 月度 | ~12 个工作日 | ✅ `available_asof` |
| 美国 CPI | `us_cpi` | FRED `CPIAUCSL` | 月度 | ~14 个工作日 | ✅ `available_asof` |
| 美元/人民币 | `usd_cny` | FRED `DEXCHUS` | 日度 | 实时 | ❌ |
| VIX (QVIX) | `vix` | AKShare `index_option_300etf_qvix` | 日度 | 实时 | ❌ |
| TIPS 收益率 | `tips_yield` | FRED `DFII10` | 日度 | 实时 | ❌ |
| EIA 原油库存 | `eia_crude_stock` | EIA 官网 XLS | 周度 | ~7 天 | ❌ |

**口径说明**：
- 月度宏观数据有 `release_date` 字段（`macro_calendar.py` 推断），用于回测防前视偏差
- `release_date` 是保守推断（非真实公告日），节假日/周末映射到下一工作日
- CPI/PMI/M2/社融的因子已统一走 `available_asof()` 过滤
- 跨品种传导因子（pmi_metals/silver/metals）已接入 `available_asof()`（2026-05-22 commit）

---

## 五、已知缺口

| 品种 | 状态 | 原因 |
|------|------|------|
| `chicken_spot`（白羽肉鸡现货） | ❌ 未接入 | 无稳定公开 API；不解析 HTML，不以白条鸡批发价冒充 |

---

## 六、价格口径选择指南

| 场景 | 推荐字段 | 原因 |
|------|----------|------|
| 回测收益 / P&L | `return_raw` | 真实可交易收益，含换月跳空 |
| 估值位置 / z-score | `close_adj` / `return_adj` | 消除换月噪声，更准确反映趋势 |
| 动量 / 波动率 | `return_raw` 或 `return_adj` | 取决于是否想捕捉换月信号 |
| 止损计算 | `close_raw` + `_volatility_stop()` | 基于真实价格波动 |
| 因子信号 | `close`（= close_adj） | 默认口径，向后兼容 |

---

## 七、DataBus 换月跳空调整算法

`DataBus._adjust_roll_gap()` 的处理逻辑：

1. 计算日收益率 `pct_change()`
2. 用 20 日滚动波动率 × 5 作为阈值，识别跳空（`|return| > threshold`）
3. 跳空后的价格整体平移，消除断点
4. 结果：`close_raw`（原始）、`close_adj`（调整后）、`close`（= adj）

**风险提示**：
- 可能把真实行情跳涨/跳跌误识别为换月
- 对政策冲击、地缘冲突、极端天气导致的真实跳空会过度平滑
- 均值回归类因子的 z-score 可能被平滑过度
- 动量/波动率类因子的真实风险可能被低估

---

*文档维护：每次新增数据源或修改换月逻辑时更新本文档。*
