# 当前任务清单：纯净建议机（Recommendation Layer）

**最后更新**: 2026-05-24 11:10  
**当前阶段**: Batch 6 完成；进入 Batch 7 解释性与有效性验证  
**范围**: 只输出买入 / 卖出 / 观望建议，不引入真实交易记录、真实持仓或账户系统。

---

## 已完成基线

方案三「现货 + 期货 + 股票/ETF 混合信号链」已完成：

- 56 条链已迁移到新结构
- DataBus 支持多驱动读取与健康状态
- MixedDriverFactor 与 3 条混合链已接入
- 现货、股票、ETF 数据源已接入
- 回测层、IC、API、推送、文档均已适配混合链
- 最新全量测试：211 passed

---

## 当前待办

### Batch 5：RecommendationV1 输出定型 ✅

- [x] **任务 33**: 定义 `RecommendationV1` 标准输出结构 ✅
- [x] **任务 34**: 新增 `core/recommendation_engine.py` ✅
- [x] **任务 35**: API 增加建议接口 (`/recommend/<chain>` + `/signal/<chain>` 新增 `recommendation` 字段) ✅
- [x] **任务 36**: 推送格式切换为“建议口径” ✅

---

### Batch 6：数据新鲜度与建议可信度 ✅

- [x] **任务 37**: 升级 `DataBus.get_driver_status()` 为数据健康详情 ✅
  - 新增 status: ok / stale / missing_known / missing_unexpected
  - 新增 last_date, lag_days, expected_frequency, max_allowed_lag, reason
  - _FRESHNESS_RULES 定义每个数据集的期望频率和最大允许延迟

- [x] **任务 38**: `driver_health` API 返回数据新鲜度 ✅
  - API 自动适配新格式，无需修改路由

- [x] **任务 39**: RecommendationEngine 根据数据健康调整建议 ✅
  - 缺失关键数据：降低 confidence
  - 数据过期：增加 data_notes / risk_notes
  - 关键驱动严重缺失(>=2)：强制 HOLD

---

### Batch 7：解释性与有效性验证

- [ ] **任务 40**: 混合因子输出 `components`
  - 例如 pork_zscore / feed_cost_change_20d / spot_change_5d / equity_momentum_20d
  - 保留最终 `factor_value`
  - 用于解释为什么建议买 / 卖 / 观望

- [ ] **任务 41**: 聚合层输出建议解释字段
  - `risk_notes`
  - `conflict_notes`
  - `driver_groups`
  - `driver_conflicts`
  - 把冲突度转成自然语言说明

- [ ] **任务 42**: 回测保持“建议有效性验证”口径
  - 买入建议后 1 / 5 / 10 / 20 日收益
  - 卖出建议后 1 / 5 / 10 / 20 日方向是否正确
  - HOLD 后波动是否收敛
  - 不做账户净值、不做持仓模拟

- [ ] **任务 43**: 新增每日总览接口
  - 今日建议买入列表
  - 今日建议卖出列表
  - 今日建议观望列表
  - 数据不足 / 冲突较高列表

- [ ] **任务 44**: 文档更新与回归测试
  - README 增加“纯净建议机”说明
  - DATA_CONTRACT_SPEC 补数据新鲜度规则
  - 全量测试通过后 commit

---

## 执行约束

1. 不解析 HTML；没有稳定接口的数据继续 known missing
2. 不冒充口径；不使用替代数据伪装真实口径
3. 保持向后兼容；旧 API / 旧 signal 字段不能破坏
4. 分批执行；每批完成后跑全量测试
5. 每批测试通过后 commit，commit 信息写清楚
6. 不引入交易账户、真实持仓、OPEN / CLOSE / ADD / REDUCE 等交易动作

---

## 下一步建议

从 **Batch 5** 开始：先实现 `RecommendationV1` 和 `core/recommendation_engine.py`，再决定 API 采用新增接口还是在现有 `/signal/<chain>` 中附加字段。
