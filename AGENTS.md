# AGENTS.md — AI 开发规则

> 本文档供 AI 编码助手读取。新增因子或体系时，AI 必须逐条遵守以下约束。

## 项目概述

quant_factors 是多因子量化分析系统，基于 AKShare + Flask，覆盖肉蛋粮/能源/金属/宏观/技术五大体系。

## 硬约束（9 条，缺一不可）

| # | 约束 | 不遵守的后果 | 涉及文件 |
|---|------|-------------|----------|
| 1 | 继承 `BaseFactor` | 没有 DataBus、自适应阈值等能力 | `factors/xxx/*.py` |
| 2 | `@FactorRegistry.register` 装饰器 | 不会出现在 `/registry` 中 | `factors/xxx/*.py` |
| 3 | `calculate()` 返回 dict | `_run_factor_chain` 拿不到数据 | `factors/xxx/*.py` |
| 4 | `signal()` 返回 dict 或 None | 信号落库、IC 快照都不会触发 | `factors/xxx/*.py` |
| 5 | 用 `self.load()` 加载数据 | 不走缓存，每次重复 I/O | `factors/xxx/*.py` |
| 6 | 用 `self._adaptive_threshold()` | 阈值写死，波动大时频繁误触发 | `factors/xxx/*.py` |
| 7 | 注册到 `chains.yaml` | `/analyze/xxx` 路由找不到因子 | `config/chains.yaml` |
| 8 | 导入到 `core/factor_runner.py.ensure_imported()` | 装饰器不执行，因子不注册 | `server.py` / `core/factor_runner.py` |
| 9 | 数据下载 + 定时刷新都要加 | 新因子没数据可算 | `download_history.py` + `server.py` |

## 因子目录分类

```
factors/
├── meat/       # 肉类：猪肉
├── feed/       # 饲料：豆粕、玉米、大豆、菜粕
├── cross/      # 跨品种联动 + 跨体系联动
│               #   品种内：猪粮比、饲料成本、压榨利润、猪鸡替代、蛋料比
│               #   跨体系：铜金比、油金传导、汇率→商品、PMI→金属
├── macro/      # 宏观：CPI、PMI、汇率、M2
├── energy/     # 能源：原油、天然气
├── metals/     # 金属：铜、铝、螺纹钢、黄金、白银
└── technical/  # 技术因子：动量、波动率、期限结构、季节性（通用，不绑定品种）
```

**规则**：
- 单品种因子放对应目录（如 `meat/`、`energy/`）
- 跨品种联动放 `cross/`（包括跨体系联动，如铜金比、油金传导）
- 通用技术因子放 `technical/`，通过 `symbol` 参数指定品种
- 鸡蛋因子已合并到 `cross/egg_feed_ratio.py`（蛋料比）
- 鸡肉因子已合并到 `cross/pig_chicken_spread.py`（猪鸡替代）
- 牛羊肉因子已删除（信号质量差，不适合个人投资者）

## 因子设计原则

### 每个因子必须有差异化逻辑

**禁止**复制粘贴同一个模板只改品种名。每个品种的经济角色不同，核心驱动不同：

| 品种 | 经济角色 | 核心驱动 | 应监测 |
|------|---------|---------|--------|
| 铜 | 工业消耗品 | 制造业需求、绿色转型 | PMI、库存、期限结构 |
| 铝 | 能源密集型工业金属 | 电力成本（占 40%） | 能源价格、减产 |
| 螺纹钢 | 建筑/基建材料 | 房地产+基建 | 季节性、库存周期 |
| 黄金 | 避险资产/货币替代 | 实际利率、美元、地缘 | 美元、VIX、通胀预期 |
| 白银 | 工业+贵金属双属性 | 光伏需求 + 跟随黄金 | 金银比、PMI、黄金走势 |
| 原油 | 能源定价锚 | 供需、地缘、OPEC | 库存、价差、美元 |
| 天然气 | 季节性+区域能源 | 天气、库存 | 季节性、油气比 |

### 新增体系必须考虑跨体系联动

新增体系时，必须同时考虑与已有体系的联动。例如：
- 化工体系依赖原油（能源体系）
- 黑色系（铁矿石→螺纹钢）与基建投资（宏观）联动
- 有色金属与 PMI（宏观）联动

跨体系联动因子统一放 `factors/cross/`，category 用 `cross/system`。

## 新增单个因子（5 步）

**第 1 步：创建因子文件**

```python
from typing import Optional, Dict, Any
from factors.base import BaseFactor
from core.factor_registry import FactorRegistry

@FactorRegistry.register(
    name="xxx", category="xxx",
    description="xxx",
    asset="xxx", data_deps=["xxx"]
)
class XxxFactor(BaseFactor):
    def calculate(self) -> Dict[str, Any]:
        df = self.load("xxx")
        # ... 差异化计算逻辑
        return result

    def signal(self) -> Optional[Dict[str, Any]]:
        data = self.calculate()
        # ... 差异化信号逻辑
        return signal_or_none

    def signal_strength(self) -> float:
        data = self.calculate()
        return self._continuous_signal(...)
```

**第 2 步：注册到 `config/chains.yaml`**

```yaml
xxx:
  category: "xxx"
  description: "xxx"
  factor_module: "factors.xxx.xxx"
  factor_class: "XxxFactor"
  asset: "xxx"
  data_deps:
    - xxx
```

**第 3 步：添加数据下载**（`download_history.py`）

**第 4 步：注册导入 + 定时刷新**（`server.py` / `core/factor_runner.py`）

在 `core/factor_runner.py.ensure_imported()` 中添加 `import factors.xxx.xxx`。
在 `server.py` 的 `_daily_data_refresh()` / `_daily_data_refresh_foreign()` 中添加数据刷新。

**第 5 步：重启服务**

## 新增一整个体系（7 步）

以"化工体系"为例，最少改 7 个文件：

1. `factors/chemical/__init__.py` — 新建，导出因子类
2. `factors/chemical/pta.py` 等 — 新建，因子实现
3. `factors/cross/pta_crude_spread.py` — 跨体系联动
4. `config/chains.yaml` — 注册链条 + 综合链条
5. `server.py` / `core/factor_runner.py` — 3 处修改（import + 定时刷新 + 综合路由）
6. `download_history.py` — 数据下载
7. `factors/__init__.py` — 导出新因子类

## 检查清单

| 检查项 | 文件 |
|--------|------|
| ☐ 因子类继承 `BaseFactor` + `@FactorRegistry.register` | `factors/xxx/*.py` |
| ☐ `calculate()` 返回 dict，`signal()` 返回 dict 或 None | `factors/xxx/*.py` |
| ☐ 数据加载用 `self.load()`，阈值用 `self._adaptive_threshold()` | `factors/xxx/*.py` |
| ☐ 因子逻辑差异化，不是复制模板改品种名 | `factors/xxx/*.py` |
| ☐ 文件头部有影响链条文档（`"""影响链条..."""`），不读代码也能看懂逻辑 | `factors/xxx/*.py` |
| ☐ `chains.yaml` 中 `factor_module` 和 `factor_class` 与代码一致 | `config/chains.yaml` |
| ☐ 综合链条（如有）的 `sub_chains` 名称与单链条名称一致 | `config/chains.yaml` |
| ☐ `download_history.py` 添加数据下载 | `download_history.py` |
| ☐ 因子导入入口已迁移到 `core/factor_runner.py.ensure_imported()` | `server.py` / `core/factor_runner.py` |
| ☐ `server.py._daily_data_refresh()` 添加定时刷新 | `server.py` |
| ☐ 综合链路 API 路由（如有） | `server.py` |
| ☐ 跨体系联动已考虑（新增体系与已有体系的传导关系） | `factors/cross/` |

## 跨体系联动关系

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