# 现货数据源与因子计算文档

**最后更新**: 2026-05-24  
**范围**: 所有现货数据源、期货数据源、因子计算公式、信号生成规则

---

## 一、数据源总览

### 1.1 现货数据（13个品种）

| 品种 | 数据名 | 来源 | 接口 | 数据格式 | 历史深度 |
|------|--------|------|------|----------|----------|
| 生猪现货 | `pork_spot` | 生意社(100ppi.com) | `futures_spot_price_daily` | date + close | 2024年起 |
| 黄金现货基准价 | `gold_spot` | 上海金交所(SGE) | `spot_golden_benchmark_sge` | date + close(早盘价) | 2016年起 |
| 白银现货基准价 | `silver_spot` | 上海金交所(SGE) | `spot_silver_benchmark_sge` | date + close(早盘价) | 2019年起 |
| 铜现货 | `copper_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(CU)` | date + close(spot_price) | 2020年起 |
| 铝现货 | `aluminum_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(AL)` | date + close(spot_price) | 2024年起 |
| 螺纹钢现货 | `rebar_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(RB)` | date + close(spot_price) | 2024年起 |
| 铁矿石现货 | `iron_ore_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(I)` | date + close(spot_price) | 2024年起 |
| 鸡蛋现货 | `egg_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(JD)` | date + close(spot_price) | 2024年起 |
| 玉米现货 | `corn_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(C)` | date + close(spot_price) | 2024年起 |
| 豆粕现货 | `soybean_meal_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(M)` | date + close(spot_price) | 2024年起 |
| 豆油现货 | `soybean_oil_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(Y)` | date + close(spot_price) | 2024年起 |
| 菜粕现货 | `rapeseed_meal_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(RM)` | date + close(spot_price) | 2024年起 |
| 国产大豆现货 | `soybean_domestic_spot` | 生意社(100ppi.com) | `futures_spot_price_daily(A)` | date + close(spot_price) | 2024年起 |

**缺失（无免费稳定接口）**:
- 鸡肉现货 (`chicken_spot`) — 无稳定公开历史接口，不使用网页HTML解析，不以白条鸡批发价冒充白羽肉鸡棚前价
- 原油现货 — AKShare无免费接口
- 进口大豆现货 — AKShare无免费接口
- 动力煤现货 — 已废弃（国家限价后失去市场化定价功能）

### 1.2 期货数据（20个品种）

| 品种 | 数据名 | 来源 | 行数 | 最新日期 |
|------|--------|------|------|----------|
| 生猪 | `pork_futures` | AKShare | 1298 | 5/22 |
| 生猪远月 | `pork_futures_far` | AKShare | 573 | 5/22 |
| 鸡蛋 | `egg_futures` | AKShare | 1543 | 5/20 |
| 玉米 | `corn_futures` | AKShare | 1543 | 5/20 |
| 豆粕 | `soybean_meal_futures` | AKShare | 1543 | 5/20 |
| 豆油 | `soybean_oil_futures` | AKShare | 1543 | 5/20 |
| 菜粕 | `rapeseed_meal_futures` | AKShare | 1543 | 5/20 |
| 国产大豆 | `soybean_domestic_futures` | AKShare | 1543 | 5/20 |
| 进口大豆 | `soybean_import_futures` | AKShare | 1543 | 5/20 |
| CBOT大豆 | `cbot_soybean` | AKShare | 2544 | 5/22 |
| 原油 | `crude_oil_futures` | AKShare | 1543 | 5/20 |
| 布伦特原油 | `brent_oil` | AKShare | 1612 | 5/18 |
| 天然气 | `natural_gas_futures` | AKShare | 2579 | 5/22 |
| 铜 | `copper_futures` | AKShare | 1543 | 5/20 |
| 铝 | `aluminum_futures` | AKShare | 1543 | 5/20 |
| 螺纹钢 | `rebar_futures` | AKShare | 1543 | 5/20 |
| 铁矿石 | `iron_ore_futures` | AKShare | 1543 | 5/20 |
| 黄金 | `gold_futures` | AKShare | 1543 | 5/20 |
| 白银 | `silver_futures` | AKShare | 1543 | 5/20 |

**已移除**: 动力煤期货 (`thermal_coal_futures`) — 2022年国家限价后失去市场化定价功能

---

## 二、现货数据在因子中的应用

### 2.1 现货数据的用途

1. **信号生成**: 现货价格变化作为信号触发条件之一
2. **基差分析**: 期货-现货价差（基差）反映市场预期
3. **价格验证**: 现货与期货价格的交叉验证
4. **推送报告**: 同时展示现货和期货的5日价格趋势

### 2.2 现货数据在推送报告中的展示

推送报告同时展示现货和期货的5日价格：

```
📊 **近5日价格:**
- 铜期货: 106750 → 104710 → 104330 → 104530 → 103950 ↓ (-2.6%)
  📍 近1年：仅94%的交易日比现在更便宜（接近顶部区间）
- 铜现货: 104278 → 104185 → 103398 → 105220 → 104575 ↑ (+0.3%)
```

### 2.3 现货/期货配对映射

| 链条 | 期货数据 | 现货数据 | 标签 |
|------|----------|----------|------|
| pork_etf | pork_futures | pork_spot | 生猪 |
| copper | copper_futures | copper_spot | 铜 |
| aluminum | aluminum_futures | aluminum_spot | 铝 |
| rebar | rebar_futures | rebar_spot | 螺纹钢 |
| iron_ore | iron_ore_futures | iron_ore_spot | 铁矿石 |
| gold | gold_futures | gold_spot | 黄金 |
| silver | silver_futures | silver_spot | 白银 |
| corn | corn_futures | corn_spot | 玉米 |
| soybean_meal | soybean_meal_futures | soybean_meal_spot | 豆粕 |
| soybean | soybean_domestic_futures | soybean_domestic_spot | 国产大豆 |
| soybean_oil | soybean_oil_futures | soybean_oil_spot | 豆油 |
| rapeseed_meal | rapeseed_meal_futures | rapeseed_meal_spot | 菜粕 |
| egg | egg_futures | egg_spot | 鸡蛋 |

---

## 三、因子计算公式详解

### 3.1 肉蛋粮体系因子

#### 3.1.1 生猪→养殖ETF (pork_etf)

**因子类**: `PorkEtfFactor` (factors/meat/pork.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
猪周期位置 = f(当前价格, 养猪成本12元/kg)
  - 深度亏损: 价格 < 10元/kg (成本线以下20%)
  - 亏损: 10元/kg ≤ 价格 < 12元/kg
  - 盈利: 12元/kg < 价格 ≤ 15元/kg
  - 暴利: 价格 > 15元/kg (成本线以上25%)
趋势判断: MA20 vs MA60
  - 向上: MA20 > MA60
  - 向下: MA20 < MA60
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 深度亏损 | BUY | 0.75 | 猪周期底部，反弹确定性高 |
| 单日涨 ≥ 3% + 趋势向上 | BUY | 0.60 | 短期动能强劲 |
| Z-score > 2 + 暴利 | SELL | 0.65 | 猪周期顶部，下跌风险大 |
| 单日跌 ≥ 3% + 趋势向下 | SELL | 0.55 | 短期下跌动能 |

**数据依赖**: `pork_futures`

#### 3.1.2 豆粕→饲料成本 (soybean_meal)

**因子类**: `SoybeanMealFactor` (factors/feed/soybean_meal.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
自适应Z阈值 = 基础阈值 × (近期波动率 / 长期波动率)
  - 近期波动率: 20日收益率标准差
  - 长期波动率: 60日收益率标准差
  - 基础阈值: 2.0
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -自适应阈值 | BUY豆粕 | 0.60 | 超卖反弹 |
| 单日涨 ≥ 4% | SELL养殖ETF | 0.65 | 饲料成本急升，养殖利润承压 |
| Z-score ≥ 自适应阈值 | SELL豆粕 | 0.55 | 超买回调 |

**数据依赖**: `soybean_meal_futures`

#### 3.1.3 玉米→饲料成本 (corn)

**因子类**: `CornFactor` (factors/feed/corn.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
自适应Z阈值 = 基础阈值 × (近期波动率 / 长期波动率)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 | BUY玉米 | 0.65 | 极端低位反弹 |
| 单日涨 ≥ 自适应阈值 | SELL养殖ETF | 0.60 | 成本上升 |
| 单日跌 ≥ 自适应阈值 | BUY养殖ETF | 0.60 | 成本下降 |

**数据依赖**: `corn_futures`

#### 3.1.4 猪粮比→收储预期 (pig_grain_ratio)

**因子类**: `PigGrainRatioFactor` (factors/cross/pig_grain_ratio.py)

**计算公式**:
```
猪粮比 = 生猪价格(元/kg) / 玉米价格(元/kg)
  - 生猪价格: pork_futures 最新收盘价
  - 玉米价格: corn_futures 最新收盘价

自适应阈值校准:
  - vol_sensitivity = 20 (比默认50更保守)
  - 一级预警: 猪粮比 < 5.0 (国家收储触发线)
  - 二级预警: 猪粮比 < 5.5 (关注收储)
  - 价格过热: 猪粮比 > 9.0 (国家抛储触发线)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 猪粮比 < 一级预警(~5.0) | BUY生猪 | 0.75 | 国家收储确定性高 |
| 猪粮比 < 二级预警(~5.5) | BUY生猪 | 0.60 | 关注收储预期 |
| 猪粮比 > 价格过热(~9.0) | SELL生猪 | 0.65 | 抛储预期 |

**数据依赖**: `pork_futures`, `corn_futures`

#### 3.1.5 饲料成本指数→养殖利润 (feed_cost)

**因子类**: `FeedCostFactor` (factors/feed/feed_cost.py)

**计算公式**:
```
饲料成本指数 = 玉米价格 × 0.60 + 豆粕价格 × 0.25 + 菜粕价格 × 0.10 + 200(固定成本)
  - 若菜粕缺失: 豆粕权重合并为 0.35 (0.25 + 0.10)

分位数 = (当前成本指数在历史中的位置) × 100%
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 单日涨 ≥ 3% | SELL养殖ETF | 0.65 | 成本急升 |
| 分位 > 90% | SELL养殖ETF | 0.60 | 成本高位 |
| 分位 < 10% | BUY养殖ETF | 0.60 | 成本低位 |

**数据依赖**: `corn_futures`, `soybean_meal_futures`, `rapeseed_meal_futures`

#### 3.1.6 压榨利润→豆粕供给 (crush_margin)

**因子类**: `CrushMarginFactor` (factors/feed/crush_margin.py)

**计算公式**:
```
压榨利润 = 豆油价格 × 0.18 + 豆粕价格 × 0.78 - 进口大豆价格 - 150(加工费)
  - 出率: 豆油18%, 豆粕78%, 损耗4%

自适应阈值:
  - 亏损阈值: 历史25%分位数
  - 盈利阈值: 历史75%分位数
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 压榨利润 < -自适应亏损阈值 | BUY豆粕 | 0.65 | 油厂停机→供给收缩 |
| 压榨利润 > 自适应盈利阈值 | SELL豆粕 | 0.60 | 满负荷→供给增加 |

**数据依赖**: `soybean_oil_futures`, `soybean_meal_futures`, `soybean_import_futures`

#### 3.1.7 蛋料比→鸡蛋信号 (egg_feed_ratio)

**因子类**: `EggFeedRatioFactor` (factors/cross/egg_feed_ratio.py)

**计算公式**:
```
饲料成本 = 玉米价格 × 0.60 + 豆粕价格 × 0.25 + 200(固定成本)
蛋料比 = 鸡蛋价格(元/斤) / 饲料成本(元/斤)
  - 鸡蛋价格: egg_futures 最新收盘价 / 500 (期货单位元/500kg → 元/斤)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 蛋料比 < 2.5 (亏损线) | BUY鸡蛋 | 0.70 | 淘汰老鸡→供给收缩 |
| 蛋料比 > 3.5 (暴利线) | SELL鸡蛋 | 0.65 | 补栏扩产→供给增加 |
| 鸡蛋单日跌 ≥ 自适应阈值 | BUY鸡蛋 | 0.55 | 超卖反弹 |

**数据依赖**: `egg_futures`, `corn_futures`, `soybean_meal_futures`

---

### 3.2 能源体系因子

#### 3.2.1 原油+EIA库存 (crude_oil)

**因子类**: `CrudeOilFactor` (factors/energy/crude_oil.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
EIA库存变化 = 本周库存 - 上周库存
库存趋势 = 近4周库存变化方向
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 库存下降 | BUY原油 | 0.70 | 超卖+需求好转 |
| 库存连续4周下降 | BUY原油 | 0.60 | 需求持续好转 |
| Z-score ≥ 2 + 库存上升 | SELL原油 | 0.65 | 超买+供给过剩 |

**数据依赖**: `crude_oil_futures`, `eia_crude_stock`

#### 3.2.2 天然气 (natural_gas)

**因子类**: `NaturalGasFactor` (factors/energy/natural_gas.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
季节性因子 = 历史同期价格分位数
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 季节性低位 | BUY天然气 | 0.65 | 超卖+季节性反弹 |
| Z-score ≥ 2 + 季节性高位 | SELL天然气 | 0.60 | 超买+季节性回调 |

**数据依赖**: `natural_gas_futures`

---

### 3.3 金属体系因子

#### 3.3.1 铜 (copper)

**因子类**: `CopperFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
PMI方向 = f(PMI数据)
  - PMI > 50: 扩张 → 利好铜
  - PMI < 50: 收缩 → 利空铜
库存趋势 = LME铜库存变化方向
期限结构 = 近月价格 / 远月价格
  - contango (近低远高): 供给充裕
  - backwardation (近高远低): 供给紧张
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + PMI扩张 | BUY铜 | 0.70 | 超卖+需求好转 |
| 期限结构 backwardation | BUY铜 | 0.60 | 供给紧张 |
| Z-score ≥ 2 + PMI收缩 | SELL铜 | 0.65 | 超买+需求下滑 |

**数据依赖**: `copper_futures`, `copper_spot`, `pmi`

#### 3.3.2 铝 (aluminum)

**因子类**: `AluminumFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
云南水电因子 = f(月份)
  - 11-4月 (枯水期): 水电不足→云南电解铝限产→供给收缩→利多铝价
  - 5-6月 (丰水期初期): 水电恢复→复产预期→偏空铝价
  - 7-10月 (丰水期): 水电充裕→满产→供给宽松→偏空铝价
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 枯水期 | BUY铝 | 0.70 | 超卖+供给收缩 |
| Z-score ≥ 2 + 丰水期 | SELL铝 | 0.60 | 超买+供给宽松 |

**数据依赖**: `aluminum_futures`, `aluminum_spot`

#### 3.3.3 螺纹钢 (rebar)

**因子类**: `RebarFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
季节性因子 = f(月份)
  - 3-5月 (春季开工): 需求旺季→利多螺纹钢
  - 6-8月 (雨季): 需求淡季→利空螺纹钢
  - 9-11月 (秋季开工): 需求旺季→利多螺纹钢
  - 12-2月 (冬季): 需求淡季→利空螺纹钢
库存周期 = 社会库存变化方向
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 春季开工 | BUY螺纹钢 | 0.70 | 超卖+需求旺季 |
| 库存连续4周下降 | BUY螺纹钢 | 0.60 | 需求好转 |
| Z-score ≥ 2 + 雨季 | SELL螺纹钢 | 0.65 | 超买+需求淡季 |

**数据依赖**: `rebar_futures`, `rebar_spot`

#### 3.3.4 铁矿石 (iron_ore)

**因子类**: `IronOreFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
成本占比 = 铁矿石价格 / 螺纹钢价格 × 100%
  - 正常范围: 40-50%
  - 高位: > 55% (钢厂利润被压缩)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 成本占比低位 | BUY铁矿石 | 0.65 | 超卖+钢厂利润改善 |
| 成本占比 > 55% | SELL铁矿石 | 0.60 | 钢厂利润被压缩 |

**数据依赖**: `iron_ore_futures`, `iron_ore_spot`, `rebar_futures`

#### 3.3.5 黄金 (gold)

**因子类**: `GoldFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
美元指数方向 = f(USD/CNY)
实际利率方向 = f(10年期国债收益率 - CPI)
通胀预期 = f(CPI数据)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| Z-score ≤ -2 + 美元走弱 | BUY黄金 | 0.70 | 超卖+避险需求 |
| 实际利率下降 | BUY黄金 | 0.60 | 黄金抗通胀 |
| Z-score ≥ 2 + 美元走强 | SELL黄金 | 0.65 | 超买+美元压制 |

**数据依赖**: `gold_futures`, `gold_spot`, `usd_cny`, `cpi`

#### 3.3.6 白银 (silver)

**因子类**: `SilverFactor` (factors/metals/metals.py)

**计算公式**:
```
Z-score = (当前价格 - 20日均值) / 20日标准差
金银比 = 黄金价格 / 白银价格
  - 正常范围: 60-80
  - 高位: > 85 (白银相对低估)
  - 低�ite: < 55 (白银相对高估)
工业需求 = f(光伏装机量)
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 金银比 > 85 | BUY白银 | 0.70 | 白银相对低估 |
| Z-score ≤ -2 + 工业需求增长 | BUY白银 | 0.65 | 超卖+需求支撑 |
| 金银比 < 55 | SELL白银 | 0.60 | 白银相对高估 |

**数据依赖**: `silver_futures`, `silver_spot`, `gold_futures`

---

### 3.4 宏观体系因子

#### 3.4.1 VIX恐慌指数 (vix)

**因子类**: `VixFactor` (factors/macro/vix.py)

**计算公式**:
```
VIX水平 = 当前VIX值
  - 正常: VIX < 20
  - 警戒: 20 ≤ VIX < 30
  - 恐慌: VIX ≥ 30
  - 极度恐慌: VIX ≥ 35
VIX变化 = 单日VIX变化幅度
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| VIX ≥ 30 + 油价暴跌 | HOLD现金 | 0.80 | 流动性危机，现金为王 |
| VIX ≥ 30 | BUY黄金 | 0.70 | 避险需求 |
| VIX < 15 + 股市高位 | SELL黄金 | 0.60 | 风险偏好升温 |

**数据依赖**: `vix`

---

## 四、混合信号链（Mixed Chains）

### 4.1 生猪现货+期货+饲料成本 → 养殖ETF (pork_stock_signal)

**因子类**: `PorkStockSignal` (factors/mixed/pork_stock_signal.py)

**计算公式**:
```
生猪周期位置 = f(pork_futures Z-score)
饲料成本变化 = (当前饲料成本 - 20日前饲料成本) / 20日前饲料成本
  - 饲料成本 = 玉米价格 × 0.60 + 豆粕价格 × 0.25
养殖ETF动量 = (当前ETF价格 - 20日前ETF价格) / 20日前ETF价格
现货确认 = (当前现货价格 - 5日前现货价格) / 5日前现货价格

综合评分 = 加权平均:
  - 生猪周期位置 (权重0.35): Z-score < -1.0 → +1.0, Z-score > 1.0 → -1.0
  - 饲料成本方向 (权重0.25): 下降>5% → +0.8, 上升>5% → -0.8
  - 养殖ETF动量 (权重0.20): 上升>5% → +0.5, 下降>10% → -0.8
  - 现货确认 (权重0.20): 上升>2% → +0.7, 下降>3% → -0.7
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 综合评分 ≥ 0.3 | BUY | 0.65 | 多重利好共振 |
| 综合评分 ≤ -0.3 | SELL | 0.55 | 多重利空共振 |
| -0.3 < 综合评分 < 0.3 | HOLD | 0.40 | 信号不明确 |

**数据依赖**: `pork_futures`, `corn_futures`, `soybean_meal_futures`, `pork_spot`, `breeding_etf`

### 4.2 黄金期货+实际利率+汇率 → 黄金ETF (gold_etf_signal)

**因子类**: `CommodityToEquitySignal` (factors/mixed/commodity_to_equity.py)

**计算公式**:
```
商品信号 = f(gold_futures Z-score)
成本驱动 = f(usd_cny 变化)
权益信号 = f(gold_etf 动量)

综合评分 = 加权平均:
  - 商品信号 (权重0.5): Z-score < -1.5 → +1.0, Z-score > 1.5 → -1.0
  - 成本驱动 (权重0.3): 人民币贬值 → +0.7, 人民币升值 → -0.7
  - 权益信号 (权重0.2): ETF动量 > 5% → +0.5, ETF动量 < -10% → -0.8
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 综合评分 ≥ 0.3 | BUY | 0.60 | 商品+汇率+权益共振 |
| 综合评分 ≤ -0.3 | SELL | 0.50 | 多重利空 |

**数据依赖**: `gold_futures`, `gold_spot`, `usd_cny`, `gold_etf`

### 4.3 原油期货+EIA库存 → 中国石油 (oil_stock_signal)

**因子类**: `CommodityToEquitySignal` (factors/mixed/commodity_to_equity.py)

**计算公式**:
```
商品信号 = f(crude_oil_futures Z-score)
成本驱动 = f(eia_crude_stock 库存变化)
权益信号 = f(petrochina_stock 动量)

综合评分 = 加权平均:
  - 商品信号 (权重0.5): Z-score < -1.5 → +1.0, Z-score > 1.5 → -1.0
  - 成本驱动 (权重0.3): 库存下降 → +0.7, 库存上升 → -0.7
  - 权益信号 (权重0.2): 股票动量 > 5% → +0.5, 股票动量 < -10% → -0.8
```

**信号规则**:
| 条件 | 方向 | 置信度 | 逻辑 |
|------|------|--------|------|
| 综合评分 ≥ 0.3 | BUY | 0.60 | 商品+库存+权益共振 |
| 综合评分 ≤ -0.3 | SELL | 0.50 | 多重利空 |

**数据依赖**: `crude_oil_futures`, `eia_crude_stock`, `petrochina_stock`

---

## 五、数据健康与置信度调整

### 5.1 数据新鲜度规则

| 数据类型 | 频率 | 最大允许延迟 |
|----------|------|-------------|
| 期货/现货/股票/ETF | daily | 5 天 |
| 周数据 (EIA) | weekly | 10 天 |
| 月度宏观 (CPI/PMI/M2/社融) | monthly | 45 天 |

### 5.2 置信度自动调整

- **过期数据**: 置信度 × 0.8
- **缺失数据**: 置信度 × 0.5
- **严重缺失(≥2个关键驱动)**: 强制 HOLD，置信度 × 0.3

---

## 六、API 接口

### 6.1 建议接口

| 接口 | 说明 |
|------|------|
| `/recommend/<chain>` | 单链条/综合链条建议（纯净建议口径） |
| `/signal/<chain>` | 信号详情 + `recommendation` 字段（向后兼容） |
| `/recommendations/daily` | 每日总览：所有链条今日建议列表 |
| `/recommendation_backtest` | 建议有效性验证回测 |
| `/driver_health` | 数据健康详情（含新鲜度） |

### 6.2 推荐报告格式

```json
{
  "chain": "copper",
  "description": "铜：工业消耗品，监测 PMI 方向 + 库存 + 期限结构",
  "recommendation": {
    "recommendation": "BUY",
    "label": "建议买入",
    "strength": 0.45,
    "confidence": 0.65,
    "reason": "Z-score < -2 + PMI扩张",
    "risk_notes": ["铜现货数据过期(7天)，建议置信度已降低"],
    "data_notes": ["数据过期: copper_spot 已过期 7 天"],
    "conflict_notes": [],
    "drivers_used": ["copper_futures", "copper_spot", "pmi"],
    "missing_drivers": [],
    "components": [
      {"name": "zscore_20d", "value": -2.1, "type": "zscore"},
      {"name": "current_price", "value": 103950.0, "type": "raw_value"}
    ],
    "generated_at": "2026-05-24T14:00:00"
  },
  "price_context": [
    {"label": "铜期货", "trend": "106750 → 103950 ↓ (-2.6%)", "position": "📍 近1年：仅94%的交易日比现在更便宜"},
    {"label": "铜现货", "trend": "104278 → 104575 ↑ (+0.3%)", "position": ""}
  ],
  "timestamp": "2026-05-24T14:00:00"
}
```

---

*文档维护：每次新增数据源、修改因子逻辑或调整信号规则时更新本文档。*
