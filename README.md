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
├── core/                    # 核心基础设施
│   ├── config.py            #   环境变量配置与 Tushare client 懒加载
│   ├── data_bus.py          #   数据缓存/读取
│   ├── data_refresh.py      #   定时数据刷新任务（国内/外盘）
│   ├── factor_runner.py     #   因子导入、实例化、执行、日志与 IC 快照
│   ├── macro_calendar.py    #   宏观数据发布日期/as-of 过滤
│   ├── scheduler.py         #   APScheduler 启动与 gunicorn 多 worker 文件锁
│   ├── push.py              #   推送渠道与信号日报格式化
│   └── signal_*.py          #   信号聚合、落库
├── server.py                # Flask API 服务（路由 + 内置定时任务）
├── download_history.py      # 历史数据一次性下载
├── setup.sh                 # 一键部署脚本
├── start.sh                 # 后台启动脚本
└── requirements.txt         # Python 依赖
```

**共计 37 个因子类（53 条分析链）**，覆盖 5 大体系 + 跨体系联动，全部通过 `@FactorRegistry.register` 装饰器自动注册。

> **开发指南**：新增因子/体系的约束和步骤见 [AGENTS.md](AGENTS.md)。

## 金融小白入门：核心概念速查

> 如果你没有金融背景，先花5分钟看完这一节，后面每个因子的"小白解读"你就能看懂了。

### 基础概念

| 概念 | 大白话解释 | 举个例子 |
|------|-----------|----------|
| **期货** | 约定未来某个时间以某个价格买卖某样东西的合同。我们分析的是期货的**价格走势**，不是真的去交割实物 | 生猪期货价格涨了 → 市场预期未来猪肉会变贵 |
| **现货** | 当下立刻能买卖的实物价格 | 菜市场猪肉价格就是现货价 |
| **ETF** | 一篮子股票的基金，可以在股票软件里像股票一样买卖 | 养殖ETF = 牧原、温氏等养猪公司的股票打包 |
| **Z-score** | 衡量当前价格在历史中处于什么位置。**0=平均水平，+2=偏高，-2=偏低** | Z-score=2.5 → 价格比历史上大多数时候都贵，可能要跌 |
| **分位/分位数** | 和Z-score类似，表示"超过了历史上百分之多少的日子" | 分位=90% → 当前价格比90%的历史日子都贵 |
| **自适应阈值** | 不是写死的数字，而是根据最近市场波动自动调整的触发线。波动大时阈值放宽，避免频繁误报 | 平时涨3%算异动，剧烈波动时可能涨5%才算 |

### 经济指标

| 概念 | 大白话解释 | 为什么重要 |
|------|-----------|------------|
| **PMI（采购经理指数）** | 每个月调查工厂采购经理，问他们"生意比上个月好了还是差了"。**50是分水岭**：>50=经济扩张，<50=经济收缩 | PMI是经济的"体温计"，领先股市1-2个月。PMI连续上升 → 工厂在备料 → 铜、铝等工业金属需求要涨 |
| **CPI（居民消费价格指数）** | 衡量物价涨跌的指标。**2-3%是温和通胀**（健康），>5%是恶性通胀（危险），<0是通缩（更危险） | CPI决定央行加息还是降息，直接影响股市和黄金 |
| **M2（广义货币供应量）** | 社会上总共有多少钱在流通。M2增速快=央行在"放水"=钱变多了 | 钱多了 → 资产价格容易涨（股市、房子、黄金） |
| **社融（社会融资规模）** | 实体经济（企业和个人）借了多少钱。社融增速快=大家愿意借钱投资/消费 | 社融是经济的"油门"，领先股市3-6个月 |
| **M2-社融剪刀差** | M2增速 - 社融增速。剪刀差大=钱印出来了但没人借 → 钱在金融系统空转；剪刀差小=钱流入了实体经济 | 剪刀差收窄 → 资金脱虚入实 → 利好股市 |
| **VIX（恐慌指数）** | 衡量市场有多害怕的指标。**<15=平静，15-25=正常，25-30=紧张，>30=恐慌** | VIX飙升 → 大家都在抢黄金避险；VIX极低 → 市场过度乐观，可能要回调 |

### 产业链概念

| 概念 | 大白话解释 | 为什么重要 |
|------|-----------|------------|
| **猪周期** | 猪肉价格每3-4年一轮的涨跌循环：肉贵→养猪的多→肉便宜→养猪的少→肉贵... | 猪周期底部买入养殖ETF，顶部卖出，是A股最经典的周期投资 |
| **猪粮比** | 生猪价格 ÷ 玉米价格。**低于5:1国家启动收储**（买入猪肉托市），高于9:1启动抛储（卖出储备压价） | 猪粮比是国家调控生猪市场的"发令枪"，确定性极高 |
| **饲料成本** | 养猪最大的成本是饲料（占60-70%），饲料主要成分是玉米（60%）和豆粕（25%） | 玉米/豆粕涨价 → 养猪成本上升 → 养殖股利润下降 |
| **压榨利润** | 大豆压榨成豆油+豆粕能赚多少钱。利润低→油厂停机→豆粕供给减少→豆粕涨价 | 压榨利润是豆粕供给的领先指标 |
| **蛋料比** | 鸡蛋价格 ÷ 饲料成本。**<2.5=养鸡亏钱**（会淘汰老鸡→鸡蛋减少→涨价），**>3.5=暴利**（会补栏→鸡蛋增加→跌价） | 蛋料比判断鸡蛋价格拐点非常准 |
| **铜金比** | 铜价 ÷ 金价。铜代表工业需求（经济好→用铜多），金代表避险需求（害怕→买黄金） | 铜金比上升=市场乐观（risk-on），下降=市场恐慌（risk-off） |
| **金银比** | 金价 ÷ 银价。历史上通常在50-80之间波动 | 金银比>80=白银相对黄金太便宜了，可能要补涨 |
| **期限结构** | 近月期货价格 vs 远月期货价格。近月>远月=Backwardation（现货紧缺），近月<远月=Contango（供应宽松） | Backwardation说明现货很抢手，价格易涨难跌 |
| **波动率** | 价格上蹿下跳的剧烈程度。波动率高=市场情绪激动，波动率低=市场平静 | 波动率从极高回落到正常 → 恐慌结束；波动率从极低突然放大 → 变盘信号 |
| **动量** | 最近涨了还是跌了。短期动量（5天）=最近趋势，长期动量（60天）=大方向 | 多周期动量同时向上 → 趋势很强，值得跟随 |

### 信号解读

| 信号 | 含义 | 你该做什么 |
|------|------|------------|
| **BUY** | 因子认为这个资产被低估了，未来可能上涨 | 可以考虑买入或关注 |
| **SELL** | 因子认为这个资产被高估了，未来可能下跌 | 可以考虑卖出或减仓 |
| **HOLD** | 因子认为方向不明确，观望 | 不动，等信号明确 |
| **置信度** | 因子对这个判断有多确定，0.5=一半把握，0.75=比较确定 | 置信度越高，历史上准确率越高 |
| **信号强度** | -1.0（强烈看空）到 +1.0（强烈看多），0=中性 | 强度绝对值越大，方向越明确 |

---

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

## 因子详解

### 跨体系联动关系

```
                    ┌──────────────┐
                    │   宏观体系    │
                    │ CPI/PMI/汇率  │
                    │ /M2/社融/VIX │
                    └──┬───┬───┬──┘
                       │   │   │
          PMI→金属 ────┘   │   └──── 汇率→进口商品(大豆/铜/原油)
                           │
          M2-社融剪刀差 ───┘
                           │
          VIX→避险资产 ────┘
                           │
                    ┌──────┴──────┐
                    │   能源体系   │
                    │ 原油/天然气  │
                    └──────┬──────┘
                           │
              原油→通胀→黄金 ─┘
                           │
                    ┌──────┴──────┐
                    │   金属体系   │
                    │ 铜/铝/螺纹钢 │
                    │ /黄金/白银   │
                    │ /铁矿石     │
                    └──┬───┬───┬──┘
                       │   │   │
         铁矿石→螺纹钢 ─┘   │   │
         铜金比→风险偏好 ───┘   │
         金银比→白银补涨 ──────┘
                           │
                    ┌──────┴──────┐
                    │ 肉蛋粮体系  │
                    │ 猪/鸡/蛋/饲料│
                    └─────────────┘
```

| 联动因子 | 方向 | 逻辑 |
|----------|------|------|
| `copper_gold_ratio` | 金属↔宏观 | 铜金比上升=风险偏好升温→利好权益；下降=避险→利好黄金 |
| `oil_gold_link` | 能源→金属 | 油价涨→通胀预期↑→黄金抗通胀需求↑ |
| `forex_commodity` | 宏观→商品 | 人民币贬值→进口大豆/铜/原油成本↑→国内期货补涨 |
| `pmi_metals` | 宏观→金属 | PMI扩张→制造业需求↑→铜/铝受益 |
| `iron_rebar_cost` | 金属内部 | 铁矿石涨→螺纹钢成本推升→钢厂挺价→螺纹钢补涨 |
| `social_financing` | 宏观→A股 | 社融增速↑+M2-社融剪刀差收窄→资金脱虚入实→利好A股 |
| `vix` | 宏观→避险 | VIX>30→市场恐慌→避险需求→利好黄金；VIX>35+油价暴跌→流动性危机→现金为王 |

---

### 一、肉蛋粮体系（full_meat_chain）

> **综合链入口**：`/analyze/full_meat_chain` — 10个子链并行计算+信号聚合去重

#### 1.1 生猪→养殖ETF（pork_etf）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/pork_etf` |
| **作用** | 监测生猪期货价格，判断猪周期位置，生成养殖ETF信号 |
| **💡 小白解读** | 猪肉价格每3-4年一个轮回。这个因子帮你判断现在是"猪价太便宜、养猪的都在亏、该涨了"还是"猪价太贵、养猪的暴赚、该跌了"。信号触发后对应的是养殖ETF（牧原、温氏等养猪股），不是让你去买生猪期货 |
| **计算逻辑** | 多窗口特征（5/10/20/60日动量、均线、波动率、RSI）；猪周期位置以牧原成本12元/kg为基准，判断深度亏损/亏损/暴利/盈利/微利；趋势判断 MA20 vs MA60 |
| **信号规则** | Z-score≤-2 + 深度亏损 → BUY（猪周期底部，置信度0.75）；单日涨≥3% + 趋势向上 → BUY（短期动能，置信度0.60）；Z-score>2 + 暴利 → SELL（猪周期顶部，置信度0.65） |
| **数据依赖** | `pork_futures` |

#### 1.2 豆粕→饲料成本（soybean_meal）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/soybean_meal` |
| **作用** | 监测豆粕价格极端值和异动，传导至养殖利润 |
| **💡 小白解读** | 豆粕是猪饲料的主要蛋白质来源。豆粕大涨=养猪成本飙升=养殖股要跌。这个因子帮你盯住豆粕的异常波动，及时预警养殖ETF的风险 |
| **计算逻辑** | 多窗口特征 + Z-score + 自适应Z阈值（60日窗口计算近期/长期波动率比） |
| **信号规则** | Z-score≤-自适应阈值 → BUY豆粕（超卖反弹）；单日涨≥4% → SELL养殖ETF（饲料成本急升） |
| **数据依赖** | `soybean_meal_futures` |

#### 1.3 玉米→饲料成本（corn）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/corn` |
| **作用** | 监测玉米价格，玉米占饲料60%，是养殖成本最大变量 |
| **💡 小白解读** | 玉米是猪饲料里占比最大的原料（60%）。玉米涨价=养猪成本直接上升。这个因子和豆粕因子配合使用，能提前预判养殖股的利润变化 |
| **计算逻辑** | 多窗口特征 + Z-score + 自适应阈值 |
| **信号规则** | Z-score≤-2 → BUY玉米（极端低位反弹）；单日涨≥自适应阈值 → SELL养殖ETF（成本上升）；单日跌≥自适应阈值 → BUY养殖ETF（成本下降） |
| **数据依赖** | `corn_futures` |

#### 1.4 大豆→进口成本（soybean）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/soybean` |
| **作用** | 监测国产大豆(A)、进口大豆(B)、CBOT大豆、汇率联动 |
| **💡 小白解读** | 中国大豆80%靠进口，所以进口大豆价格+人民币汇率共同决定了实际成本。人民币贬值=进口大豆变贵=豆粕成本上升。这个因子同时盯住国内外两个市场 |
| **计算逻辑** | 国产/进口大豆价格与涨跌幅；CBOT大豆 × USD/CNY = 进口成本指数 |
| **信号规则** | 进口大豆涨≥3% → BUY豆粕（成本推升）；进口大豆跌≥3% → BUY养殖ETF（成本下降） |
| **数据依赖** | `soybean_domestic_futures`, `soybean_import_futures`, `cbot_soybean`, `usd_cny` |

#### 1.5 菜粕→蛋白替代（rapeseed_meal）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/rapeseed_meal` |
| **作用** | 监测豆粕/菜粕比，判断蛋白替代关系（豆粕蛋白43% vs 菜粕36%） |
| **💡 小白解读** | 豆粕和菜粕都是蛋白饲料，可以互相替代。豆粕太贵时饲料厂会多用菜粕，推高菜粕价格。这个因子通过比价关系捕捉替代需求 |
| **计算逻辑** | 豆粕/菜粕价格比 |
| **信号规则** | 豆粕/菜粕比>1.3 → BUY菜粕（替代需求增加）；豆粕/菜粕比<0.9 → SELL菜粕（菜粕高估） |
| **数据依赖** | `soybean_meal_futures`, `rapeseed_meal_futures` |

#### 1.6 猪粮比→收储预期（pig_grain_ratio）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/pig_grain_ratio` |
| **作用** | 猪粮比是国家调控生猪市场的核心指标，触发收储/抛储 |
| **💡 小白解读** | 这是整个肉蛋粮体系中**确定性最高**的因子。国家明文规定：猪粮比<5:1就启动收储（买入猪肉托市），>9:1就抛储（卖出储备压价）。跟着国家走，胜率极高 |
| **计算逻辑** | 猪粮比 = 生猪价格 / 玉米价格；自适应阈值校准（vol_sensitivity=20，比默认50更保守） |
| **信号规则** | 猪粮比<一级预警(自适应~5.0) → BUY生猪（收储确定性高，置信度0.75）；猪粮比<二级预警(自适应~5.5) → BUY生猪（关注收储，置信度0.60）；猪粮比>价格过热(自适应~9.0) → SELL生猪（抛储预期，置信度0.65） |
| **数据依赖** | `pork_futures`, `corn_futures` |

#### 1.7 饲料成本指数→养殖利润（feed_cost）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/feed_cost` |
| **作用** | 综合玉米60%+豆粕25%+菜粕10%+固定200元，计算饲料成本指数 |
| **💡 小白解读** | 把玉米、豆粕、菜粕按实际配方比例合成一个"饲料成本指数"。这个指数涨了=养猪成本全面上升=养殖股利润承压。一个数字看清饲料成本全貌 |
| **计算逻辑** | 加权求和；菜粕缺失时豆粕权重合并为35%（0.25+0.10） |
| **信号规则** | 单日涨≥3% → SELL养殖ETF；分位>90% → SELL养殖ETF（成本高位）；分位<10% → BUY养殖ETF（成本低位） |
| **数据依赖** | `corn_futures`, `soybean_meal_futures`, `rapeseed_meal_futures` |

#### 1.8 压榨利润→豆粕供给（crush_margin）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/crush_margin` |
| **作用** | 大豆压榨利润 = 豆油×0.18 + 豆粕×0.78 - 进口大豆 - 150元加工费 |
| **💡 小白解读** | 油厂买大豆压榨成豆油和豆粕卖钱。利润高→油厂拼命压榨→豆粕供给增加→豆粕跌价。利润低甚至亏钱→油厂停机→豆粕供给减少→豆粕涨价。这个因子通过油厂行为预判豆粕供给变化 |
| **计算逻辑** | 标准大豆压榨公式，出率0.18+0.78=0.96，剩余4%损耗 |
| **信号规则** | 压榨利润< -自适应亏损阈值 → BUY豆粕（油厂停机→供给收缩）；压榨利润> 自适应盈利阈值 → SELL豆粕（满负荷→供给增加） |
| **数据依赖** | `soybean_oil_futures`, `soybean_meal_futures`, `soybean_import_futures` |

#### 1.9 猪鸡替代→鸡肉信号（pig_chicken_spread）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/pig_chicken_spread` |
| **作用** | 猪价/鸡价比>2.5→猪肉太贵→消费者转向鸡肉 |
| **💡 小白解读** | 猪肉和鸡肉是餐桌上的替代品。猪肉太贵了，老百姓就多吃鸡肉，鸡肉需求增加→涨价。这个因子通过猪鸡比价关系，捕捉消费替代效应 |
| **计算逻辑** | 生猪期货价 / 鸡肉现货价 |
| **信号规则** | 猪鸡比>2.5 → BUY鸡肉概念股；猪鸡比<1.5 → SELL鸡肉概念股；鸡肉现货单日涨≥3% → BUY |
| **数据依赖** | `pork_futures`, `chicken_spot` |

#### 1.10 蛋料比→鸡蛋信号（egg_feed_ratio）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/egg_feed_ratio` |
| **作用** | 蛋料比 = 鸡蛋价格(元/斤) / 饲料成本(元/斤)，判断蛋鸡养殖利润 |
| **💡 小白解读** | 蛋料比<2.5=养鸡亏钱→养殖户淘汰老鸡→鸡蛋供给减少→鸡蛋涨价。蛋料比>3.5=养鸡暴利→养殖户大量补栏→鸡蛋供给增加→鸡蛋跌价。这个逻辑在历史上非常准，是判断鸡蛋价格拐点的核心指标 |
| **计算逻辑** | 饲料成本 = 玉米×0.60 + 豆粕×0.25 + 200（固定）；鸡蛋价格(元/斤) = 期货价/500（期货单位元/500kg→元/斤需除以500） |
| **信号规则** | 蛋料比<2.5（亏损线）→ BUY鸡蛋（淘汰老鸡→供给收缩）；蛋料比>3.5（暴利线）→ SELL鸡蛋（补栏扩产→供给增加）；鸡蛋单日跌≥自适应阈值 → BUY（超卖反弹） |
| **数据依赖** | `egg_futures`, `corn_futures`, `soybean_meal_futures` |

---

### 二、能源体系（energy_chain）

> **综合链入口**：`/analyze/energy` — 5个子链并行计算+信号聚合去重

#### 2.1 原油+EIA库存（crude_oil）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/crude_oil` |
| **作用** | 原油价格 + EIA库存变化 → 油价方向 |
| **💡 小白解读** | 原油是"工业的血液"，油价涨跌影响几乎所有商品。EIA库存是美国能源部每周公布的原油库存数据：库存减少=需求旺盛=利好油价，库存增加=供给过剩=利空油价。这个因子把价格和库存结合起来判断方向 |
| **计算逻辑** | 多窗口特征 + Z-score + EIA库存变化 |
| **信号规则** | EIA大幅去库+Z-score<1.5 → BUY；EIA大幅累库 → SELL；Z-score≤-2 → BUY（超卖）；Z-score≥2 → SELL（超买）；单日涨≥自适应阈值 → BUY（短期动能） |
| **数据依赖** | `crude_oil_futures`, `eia_crude_stock` |

#### 2.2 天然气季节性（natural_gas）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/natural_gas` |
| **作用** | 天然气季节性 + 5年价格分位 |
| **💡 小白解读** | 天然气有极强的季节性规律：冬天取暖需求暴增（12-2月旺季），夏天发电需求增加（6-8月次旺季），春秋需求低迷（淡季）。这个因子利用季节性规律+当前价格在历史中的位置，判断天然气的买卖时机 |
| **计算逻辑** | 当前月份判断季节（12-2月冬季取暖旺季→利多；6-8月夏季发电旺季→偏多；3-5月/9-11月淡季→偏空）+ 5年价格分位 |
| **信号规则** | Z-score≤-2+旺季 → BUY（季节性需求+超卖）；Z-score≥2+淡季 → SELL（淡季+超买） |
| **数据依赖** | `natural_gas_futures` |

#### 2.3 油气比→均值回归（oil_gas_ratio）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/oil_gas_ratio` |
| **作用** | 原油/天然气比值，极端值回归 |
| **💡 小白解读** | 原油和天然气在能源领域有一定替代关系。油气比太高=原油相对天然气太贵了→天然气可能要补涨。油气比太低=天然气相对原油太贵了→天然气可能要回调。这是一个"均值回归"策略 |
| **计算逻辑** | 油气比 + 历史分位 |
| **信号规则** | 分位≥80% → BUY天然气（相对原油低估）；分位≤20% → SELL天然气（相对原油高估） |
| **数据依赖** | `crude_oil_futures`, `natural_gas_futures` |

#### 2.4 布伦特原油→中国石油（oil_assets）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/oil_assets` |
| **作用** | 布伦特原油异动→中国石油股价 |
| **💡 小白解读** | 布伦特原油是全球油价基准，中国石油（601857）的股价和油价高度相关。油价大涨→中石油利润暴增→股价跟涨。这个因子捕捉油价异动对石油股的影响 |
| **计算逻辑** | 布伦特原油涨跌幅 |
| **信号规则** | 单日涨≥5% → BUY中国石油；单日跌≥5% → SELL中国石油 |
| **数据依赖** | `brent_oil` |

#### 2.5 原油→通胀→黄金（oil_gold_link）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/oil_gold_link` |
| **作用** | 油价上涨→通胀预期→黄金抗通胀需求；油价暴跌→恐慌→黄金避险 |
| **💡 小白解读** | 原油和黄金之间有一条重要的传导链：油价涨→物价涨（通胀）→钱不值钱了→大家买黄金保值。反之油价暴跌→市场恐慌→也买黄金避险。这个因子监测这条传导链是否通畅，捕捉黄金的补涨机会 |
| **计算逻辑** | 原油/黄金涨跌幅 + 60日相关性 + 自适应阈值（vol_sensitivity=30） |
| **信号规则** | 原油20日涨>自适应阈值+黄金滞涨 → BUY黄金（通胀未定价）；原油20日跌>自适应阈值 → BUY黄金（恐慌避险）；相关性>0.5+油价涨>自适应阈值 → BUY黄金（传导有效） |
| **数据依赖** | `crude_oil_futures`, `gold_futures` |

---

### 三、金属体系（metals_chain）

> **综合链入口**：`/analyze/metals` — 9个子链并行计算+信号聚合去重

#### 3.1 铜+PMI（copper）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/copper` |
| **作用** | 铜是工业金属之王（"铜博士"），PMI是核心驱动 |
| **💡 小白解读** | 铜被称为"铜博士"，因为它能提前反映经济好坏：经济好→工厂开工→用铜多→铜价涨。PMI是制造业的体温计，PMI>50说明工厂在扩张→铜需求增加。这个因子把PMI和铜价结合起来，判断铜的买卖时机 |
| **计算逻辑** | 多窗口特征 + PMI数据 |
| **信号规则** | PMI>50+PMI↑+铜Z-score<1 → BUY（需求改善未定价）；Z-score≤-2 → BUY（超卖）；趋势下跌+Z-score<-1.5 → BUY（破位超卖） |
| **数据依赖** | `copper_futures`, `pmi` |

#### 3.2 铝+动力煤成本（aluminum）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/aluminum` |
| **作用** | 铝是能源密集型金属，电力成本占40% |
| **💡 小白解读** | 铝的生产极度耗电（电费占成本40%），所以铝价和能源价格密切相关。动力煤涨价→电价上涨→铝成本上升→铝价上涨。另外云南水电有季节性：枯水期（11-4月）电力不足限产，丰水期（6-10月）电力充足复产。这个因子同时考虑能源成本和季节性 |
| **计算逻辑** | 铝价 + 动力煤20日涨跌 + 云南水电季节性（枯水期11-4月限产、丰水期6-10月复产） |
| **信号规则** | 动力煤20日涨>10%+Z-score<1 → BUY（成本推升+减产）；动力煤20日跌>10%+Z-score>-1 → SELL（成本下降+复产）；Z-score≤-2 → BUY（超卖+成本支撑） |
| **数据依赖** | `aluminum_futures`, `thermal_coal_futures` |

#### 3.3 螺纹钢季节性（rebar）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/rebar` |
| **作用** | 螺纹钢季节性 + 库存周期 |
| **💡 小白解读** | 螺纹钢是盖房子的钢筋，需求有极强的季节性：春天（3-5月）工地开工→需求旺，秋天（9-11月）赶工→次旺季，冬天太冷夏天太热→工地停工→淡季。这个因子利用季节性规律，在旺季前布局、淡季前撤退 |
| **计算逻辑** | 多窗口特征 + 季节判断（3-5月春季旺季、9-11月秋季旺季、12-2月冬季淡季、6-8月夏季淡季） |
| **信号规则** | 旺季+Z-score<0+趋势下跌 → BUY（旺季前布局）；淡季+Z-score>1.5 → SELL（淡季高估）；Z-score≤-2 → BUY（超卖） |
| **数据依赖** | `rebar_futures` |

#### 3.4 黄金多驱动（gold）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/gold` |
| **作用** | 黄金受实际利率、美元、通胀、恐慌多重驱动 |
| **💡 小白解读** | 黄金不产生利息，所以它的核心对手是"实际利率"（=名义利率-通胀）。实际利率下降→持有黄金的机会成本降低→黄金涨。另外，人民币贬值→国内黄金涨（因为黄金是美元计价，换算成人民币更贵了）。这个因子同时监测这四个驱动力 |
| **计算逻辑** | 多窗口特征 + TIPS收益率（实际利率） + 汇率 + 原油 |
| **信号规则** | TIPS收益率下降 → BUY（实际利率下行）；人民币贬值 → BUY（本币计价黄金上涨）；原油大涨+黄金滞涨 → BUY（通胀预期）；Z-score≤-2 → BUY（超卖） |
| **数据依赖** | `gold_futures`, `tips_yield`, `usd_cny`, `crude_oil_futures` |

#### 3.5 白银双属性（silver）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/silver` |
| **作用** | 白银50%贵金属+50%工业属性 |
| **💡 小白解读** | 白银有双重身份：一半跟着黄金走（贵金属避险），一半跟着经济走（工业用途，如光伏、电子）。金银比>80=白银相对黄金太便宜→白银可能补涨。PMI>50=工业需求好→白银的工业属性受益。这个因子同时从两个角度判断白银 |
| **计算逻辑** | 金银比 + 黄金涨幅 + PMI |
| **信号规则** | 金银比分位≥90% → BUY白银（极度低估）；黄金20日涨>3%+白银滞涨 → BUY白银（补涨）；PMI>50+PMI↑+白银Z-score<0 → BUY白银（工业需求）；金银比Z-score≤-2 → SELL白银（过度上涨） |
| **数据依赖** | `silver_futures`, `gold_futures`, `pmi` |

#### 3.6 铁矿石→螺纹成本（iron_ore）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/iron_ore` |
| **作用** | 铁矿石占螺纹钢成本50%+，是螺纹钢最重要的成本驱动因子 |
| **💡 小白解读** | 生产1吨螺纹钢需要1.6吨铁矿石，所以铁矿石价格直接决定了螺纹钢的成本。铁矿石大涨→钢厂成本飙升→要么涨价（螺纹钢跟涨），要么亏钱减产（供给收缩→螺纹钢涨）。这个因子通过成本传导预判螺纹钢方向 |
| **计算逻辑** | 铁矿石价格 + 钢厂利润 = 螺纹钢 - 铁矿石×1.6 - 800（1.6吨铁矿/吨螺纹） |
| **信号规则** | 铁矿石5日涨≥5% → BUY螺纹钢（成本推升）；铁矿石Z-score>2 → BUY螺纹钢（成本强支撑）；钢厂利润<-200 → BUY螺纹钢（减产→供给收缩）；钢厂利润>500 → SELL螺纹钢（增产→供给增加） |
| **数据依赖** | `iron_ore_futures`, `rebar_futures` |

#### 3.7 铜金比→风险偏好（copper_gold_ratio）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/copper_gold_ratio` |
| **作用** | 铜金比 = 工业需求/避险需求，反映市场风险偏好。铜=经济晴雨表，金=恐慌指数 |
| **💡 小白解读** | 铜金比是市场上最经典的"风险偏好温度计"。铜金比上升=大家看好经济、愿意冒险（买铜卖金），铜金比下降=大家害怕、躲进黄金避险。这个因子帮你判断当前市场是"贪婪"还是"恐惧" |
| **计算逻辑** | 铜价/金价 + 历史分位 + Z-score |
| **信号规则** | 分位≤10% → BUY黄金（极端风险厌恶）；Z-score≤-2 → BUY黄金（风险偏好急降）；分位≥90% → BUY沪深300（极端风险偏好） |
| **数据依赖** | `copper_futures`, `gold_futures` |

#### 3.8 PMI→金属需求（pmi_metals）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/pmi_metals` |
| **作用** | PMI是铜/铝需求的领先指标，领先金属需求约1-2个月 |
| **💡 小白解读** | PMI是工厂采购经理的信心指数，PMI上升=工厂准备扩大生产→要买更多铜和铝。PMI领先金属价格1-2个月，所以PMI拐头时金属价格可能还没动，这是提前布局的窗口期 |
| **计算逻辑** | PMI + 铜/铝20日涨跌 |
| **信号规则** | PMI>51+加速上升+铜涨<2% → BUY铜（需求未定价）；PMI<49+加速下降 → SELL铜（需求萎缩）；PMI>50+上升 → BUY铝（建筑+汽车需求） |
| **数据依赖** | `pmi`, `copper_futures`, `aluminum_futures` |

#### 3.9 铁矿→螺纹成本传导（iron_rebar_cost）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/iron_rebar_cost` |
| **作用** | 铁矿石/螺纹钢比值→成本传导效率 |
| **💡 小白解读** | 铁矿石是螺纹钢的原料，正常情况下铁矿涨→螺纹钢跟涨。但有时候铁矿涨了螺纹钢没跟，说明传导不畅（可能是需求不好），这时候比值会异常。这个因子通过监测铁矿/螺纹比的极端值，捕捉螺纹钢的补涨或补跌机会 |
| **计算逻辑** | 铁矿/螺纹比 + Z-score + 5日背离度 + 钢厂利润（螺纹钢 - 铁矿×1.6 - 800） |
| **信号规则** | 比值Z-score>2+利润<200 → BUY螺纹钢（成本推升+利润压缩）；背离度>5%+利润<0 → BUY螺纹钢（铁矿领涨+钢厂亏损）；比值Z-score<-2+利润>400 → SELL螺纹钢（成本下移+高利润） |
| **数据依赖** | `iron_ore_futures`, `rebar_futures` |

---

### 四、宏观体系（macro_chain）

> **综合链入口**：`/analyze/macro` — 10个子链并行计算+信号聚合去重

#### 4.1 CPI→消费板块（cpi）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/cpi` |
| **作用** | CPI水平判断通胀环境，影响消费板块 |
| **💡 小白解读** | CPI告诉你物价涨了多少。温和通胀（0-2%）=经济健康，利好消费股。恶性通胀（>5%）=钱不值钱了，央行要加息，利空股市。通缩（<0%）=大家都不花钱等降价，经济衰退，利空股市。这个因子帮你判断当前处于哪种通胀环境 |
| **计算逻辑** | 读取CPI月度数据，判断趋势和通胀区间 |
| **信号规则** | 温和通胀(0~2%) → BUY消费ETF；恶性通胀(>5%) → SELL消费ETF；通缩(<0) → SELL消费ETF |
| **数据依赖** | `cpi` |

#### 4.2 PMI→经济周期（pmi）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/pmi` |
| **作用** | PMI方向变化判断经济周期位置 |
| **💡 小白解读** | PMI连续2个月上升=经济在好转，即使还在50以下（收缩区间），也说明"最差的时候过去了"，可以左侧布局。PMI连续2个月下降=经济在恶化，即使还在50以上，也要警惕拐点。这个因子关注的是PMI的**方向变化**，而不是绝对值 |
| **计算逻辑** | 连续上升/下降月数统计 |
| **信号规则** | 连续2月↑+PMI>50 → BUY沪深300（扩张确认）；连续2月↑+PMI<50 → BUY沪深300（收缩收窄→左侧布局）；连续2月↓+PMI<50 → SELL沪深300（收缩确认） |
| **数据依赖** | `pmi` |

#### 4.3 汇率→A股（forex）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/forex` |
| **作用** | 人民币贬值→外资流出→A股承压 |
| **💡 小白解读** | 人民币贬值=外资持有的A股按美元计算缩水了→外资可能卖出A股撤离→A股跌。反之人民币升值→外资涌入→A股涨。这个因子帮你盯住汇率异动对A股的影响 |
| **计算逻辑** | USD/CNY汇率变化 + Z-score |
| **信号规则** | 单日贬值≥0.5% → SELL沪深300；Z-score>2 → SELL沪深300（极端贬值位） |
| **数据依赖** | `usd_cny` |

#### 4.4 M2→流动性（money_supply）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/money_supply` |
| **作用** | M2增速判断流动性环境 |
| **💡 小白解读** | M2=社会上所有的钱。M2增速>12%=央行在大量放水→钱多了总要找去处→股市、房市、黄金容易涨。M2增速<8%=央行在收紧→钱少了→资产价格承压。这个因子帮你判断"水龙头"是开着还是关着 |
| **计算逻辑** | M2同比增速 + 趋势判断 |
| **信号规则** | M2>12%+加速上行 → BUY沪深300；M2<8%+加速下行 → SELL沪深300 |
| **数据依赖** | `m2` |

#### 4.5 社融→A股领先指标（social_financing）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/social_financing` |
| **作用** | 社融增速 + M2-社融剪刀差，判断资金流向 |
| **💡 小白解读** | 社融=实体经济借了多少钱。社融增速高=企业和个人愿意借钱→经济有活力→利好股市。M2-社融剪刀差=钱印出来了但没人借（在金融系统空转）→剪刀差收窄说明钱终于流入实体经济了→这是股市的强烈利好信号 |
| **计算逻辑** | 社融增速 = 近3月均值/去年同期均值 - 1；M2-社融剪刀差 = M2增速 - 社融增速 |
| **信号规则** | 社融>12%+剪刀差<1（资金脱虚入实）→ strong_buy；社融>10% → buy；社融<8%+剪刀差>2（资金淤积）→ sell |
| **数据依赖** | `social_financing`, `m2` |

#### 4.6 CBOT大豆→进口成本（cbot_soybean）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/cbot_soybean` |
| **作用** | CBOT大豆是全球大豆定价锚，影响进口成本 |
| **💡 小白解读** | CBOT是美国芝加哥的大豆期货，全球大豆价格都跟着它走。中国大豆80%靠进口，CBOT大豆涨了=中国进口成本上升=豆粕成本上升。这个因子帮你盯住全球大豆定价锚的变化 |
| **计算逻辑** | CBOT价格 + Z-score + 进口成本(CBOT×汇率) |
| **信号规则** | 单日涨≥3% → BUY豆粕；单日跌≥3% → SELL豆粕；Z-score>2 → BUY豆粕（全球偏紧）；Z-score<-2 → SELL豆粕（全球宽松） |
| **数据依赖** | `cbot_soybean`, `usd_cny` |

#### 4.7 VIX→风险偏好（vix）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/vix` |
| **作用** | VIX恐慌指数判断市场风险偏好 |
| **💡 小白解读** | VIX是市场的"恐惧温度计"。VIX>30=市场很害怕→大家抢黄金避险→黄金涨。VIX>35=极度恐慌→可能发生流动性危机（什么都跌，现金为王）。VIX<12=市场过度乐观→乐极生悲，可能要回调。这个因子帮你判断市场情绪处于什么状态 |
| **计算逻辑** | VIX当前值 + Z-score + 流动性危机检测（油价暴跌+VIX飙升） |
| **信号规则** | VIX>30+无流动性危机 → BUY黄金（避险）；VIX>35 → BUY沪深300（极度恐慌后反弹）；VIX<12 → SELL沪深300（过度乐观）；流动性危机 → SELL黄金（现金为王） |
| **数据依赖** | `vix`, `crude_oil_futures` |

#### 4.8 美国CPI→黄金（cpi_gold）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/cpi_gold` |
| **作用** | 美国CPI偏离预期→实际利率预期→黄金 |
| **💡 小白解读** | 美国CPI超预期=通胀比想的更严重→美联储可能加息→实际利率上升→黄金跌（因为黄金不产生利息，加息后持有黄金的机会成本更高了）。CPI低于预期=通胀没那么严重→美联储可能降息→黄金涨。这个因子捕捉美国通胀数据公布后的黄金短线机会 |
| **计算逻辑** | CPI实际值 - 预期值(默认0.3%) |
| **信号规则** | CPI超预期≥0.2% → SELL黄金（美联储偏鹰）；CPI低于预期≥0.2% → BUY黄金（美联储偏鸽） |
| **数据依赖** | `us_cpi` |

#### 4.9 汇率→进口商品成本（forex_commodity）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/forex_commodity` |
| **作用** | 人民币贬值→进口商品成本上升。大豆进口依赖度>80%，铜>70%，原油>70% |
| **💡 小白解读** | 人民币贬值意味着用人民币买进口商品更贵了。中国大量进口大豆、铜、原油，人民币贬值5%=这些商品的进口成本直接涨5%。这个因子帮你捕捉汇率变化对进口商品价格的传导效应 |
| **计算逻辑** | USD/CNY 5日涨跌 + 大豆/铜/原油价格 |
| **信号规则** | 人民币5日贬>1%+大豆滞涨 → BUY豆粕（传导滞后）；人民币5日贬>2% → BUY豆粕（系统性成本上升）；人民币5日升>1% → SELL豆粕（成本下降） |
| **数据依赖** | `usd_cny`, `soybean_import_futures`, `copper_futures`, `crude_oil_futures` |

---

### 五、技术因子（technical）

> 技术因子为通用因子，通过 `symbol` 参数指定品种，在 chains.yaml 中配置多实例

#### 5.1 多周期动量（momentum）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/momentum`（生猪）、`/analyze/momentum_copper`（铜）、`/analyze/momentum_crude`（原油）、`/analyze/momentum_gold`（黄金）、`/analyze/momentum_rebar`（螺纹钢） |
| **作用** | 5/20/60日动量共振 + 动量加速/衰减 |
| **💡 小白解读** | 动量就是"最近涨了还是跌了"。这个因子同时看三个时间维度：5天（短期趋势）、20天（中期趋势）、60天（长期趋势）。三个周期同时向上=趋势很强，值得跟随。另外还检测"加速"（涨得越来越快）和"衰减"（涨不动了），帮你判断趋势是刚开始还是快结束了 |
| **计算逻辑** | 加权平均（短期30%+中期40%+加速30%），tanh归一化到[-1,1]；内置波动率过滤：低波动→趋势市→动量可靠，高波动→震荡市→动量打折 |
| **信号规则** | 动量得分>0.5 → BUY（多周期共振向上）；动量得分<-0.5 → SELL（多周期共振向下）；低波动时置信度0.65，高波动时0.40 |
| **数据依赖** | 由 `symbol` 参数指定 |

#### 5.2 波动率锥（volatility）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/volatility`（生猪）、`/analyze/volatility_copper`（铜）、`/analyze/volatility_crude`（原油）、`/analyze/volatility_gold`（黄金）、`/analyze/volatility_rebar`（螺纹钢） |
| **作用** | 短期/长期波动率比→波动率回归。不判断方向，主要用于风险管理和过滤动量信号 |
| **💡 小白解读** | 波动率就是价格上蹿下跳的剧烈程度。这个因子比较短期波动和长期波动：短期波动远大于长期=市场情绪激动→波动率通常会回落（回归正常）。短期波动远小于长期=市场太安静了→可能要变盘。注意：这个因子**不判断涨跌方向**，只告诉你"现在市场是激动还是平静" |
| **计算逻辑** | 5日/20日/60日波动率 + 比值；比值>1.5=高波动，<0.5=低波动，0.8~1.2=正常 |
| **信号规则** | 比值>2.0 → SELL（极端高波动→回归）；比值<0.3 → BUY（极端低波动→突破） |
| **数据依赖** | 由 `symbol` 参数指定 |

#### 5.3 期限结构（term_structure）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/term_structure` |
| **作用** | 近远月价差→现货供需格局。Backwardation=现货紧缺，Contango=供应宽松 |
| **💡 小白解读** | 期货有不同月份：近月（马上到期的）和远月（几个月后到期的）。近月比远月贵=Backwardation=现货很紧缺，大家愿意出高价立刻拿到货→价格易涨难跌。近月比远月便宜=Contango=供应充足，不着急买→价格承压。这个因子通过近远月价差判断现货的供需紧张程度 |
| **计算逻辑** | 近月-远月价差 + 历史分位 |
| **信号规则** | Backwardation+分位>90% → BUY（现货紧缺→近月强势）；Contango+分位<10% → SELL（供应过剩→近月弱势） |
| **数据依赖** | `pork_futures`, `pork_futures_far` |

#### 5.4 季节性（seasonality）

| 项目 | 内容 |
|------|------|
| **入口** | `/analyze/seasonality`（生猪）、`/analyze/seasonality_copper`（铜）、`/analyze/seasonality_crude`（原油）、`/analyze/seasonality_gold`（黄金）、`/analyze/seasonality_rebar`（螺纹钢） |
| **作用** | 历史同期统计→当月季节性方向。至少需要3年历史数据 |
| **💡 小白解读** | 很多商品有固定的季节性规律。比如生猪：春节前需求旺→涨价，节后需求淡→跌价。这个因子统计过去几年每个月的平均涨跌和胜率，告诉你"历史上这个月涨的概率有多大"。如果历史上这个月70%的时间都在涨，那今年也大概率涨 |
| **计算逻辑** | 按月分组计算历史均收益和胜率 |
| **信号规则** | 均收益>1%+胜率>60% → BUY（季节性强势）；均收益<-1%+胜率<40% → SELL（季节性弱势） |
| **数据依赖** | 由 `symbol` 参数指定 |

---

### 信号聚合与相关性去重

综合链（`full_meat_chain`/`energy`/`metals`/`macro`）使用 `SignalAggregator` 进行多因子信号融合：

**聚合模式**：weighted（按置信度加权融合，默认）/ voting（少数服从多数投票）/ strongest（取信号强度最大）

**相关性去重分组**：

| 分组 | 成员 | 逻辑 |
|------|------|------|
| `corn_feed` | corn_surge, feed_cost_high, feed_cost_surge | 玉米涨→饲料成本涨，信号重叠 |
| `soybean_meal` | soybean_meal_surge, feed_cost_high, cbot_soybean_surge | 豆粕涨→饲料成本涨，CBOT→豆粕 |
| `pork_cycle` | pork_cycle_bottom, pig_grain_level1, pig_grain_level2 | 猪周期底部信号重叠 |
| `iron_steel` | iron_ore_surge, iron_ore_high_zscore, steel_loss_cut, iron_rebar_cost_push, iron_lead_rebar | 铁矿→螺纹信号重叠 |
| `gold_drivers` | gold_tips_low, gold_rmb_depreciation, gold_oil_inflation, gold_vix_high | 黄金多驱动同时触发 |

去重算法：`decay = 1.0 / sqrt(n)`，例如3个重叠信号各降权至约0.577。

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

服务启动时自动注册定时任务（调度器启动在 `core/scheduler.py`，具体数据刷新任务在 `core/data_refresh.py`），**不需要额外配置 crontab**。Gunicorn 多 worker 部署时通过文件锁保证只有一个 worker 启动调度器：

| 时间 | 任务 | 说明 |
|------|------|------|
| 每天 18:00 | 国内数据刷新 | 从 AKShare/Tushare 等数据源拉取最新行情，覆盖 parquet 文件 |
| 每天 06:00 | 外盘数据刷新 | 拉取外盘/海外数据 |
| 每天 18:30 | IC 计算 | 计算所有因子的 Rank IC，写入 ic_monitor.db |
| 每天 18:35 | 推送日报 | 对综合链条生成报告并发送到已配置渠道 |

依赖 `apscheduler` 库（已在 requirements.txt 中）。如果未安装，服务会在启动时报出清晰错误。Tushare 数据刷新需要运行环境设置 `TUSHARE_TOKEN`，不要把 token 写进源码。

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