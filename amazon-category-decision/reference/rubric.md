# 判断规则 · Rubric

所有报告共用这一套门槛、权重和结论规则。数字来自 `data.json`；判断写进 `narrative.json`。

## 1. 五个 hard gates

| Gate | 看什么 | pass | warn | fail |
| --- | --- | --- | --- | --- |
| 需求 | 规模、同比、价格趋势、季节性、搜索与成交是否同向 | 规模 > $20M/年；同比 ≥ 0%；峰谷 < 2.5× | 同比 -15% ~ 0%，或搜索/成交背离 | 同比 < -15%，或规模 < $10M/年，或峰谷 > 4× |
| 竞争 | TOP3、CR10、Amazon 自营、评论墙、内容 | TOP3 < 35%；Amazon < 30%；低评论 ASIN 仍能进首页 | TOP3 35–50% 或 Amazon 30–50% | TOP3 > 50% 或 Amazon > 50%，且评论墙高 |
| 经济性 | 目标价下 contribution / margin；低价带是否可覆盖 FBA+广告 | margin ≥ 20% | 10% ≤ margin < 20% | margin < 10%，或 contribution < 0 |
| 供应链 | MOQ、交期、包装、认证、专利、质保 | 已有报价 + 认证 + 包装方案 | 部分有，关键项待确认 | 关键项缺失且无法解决 |
| 差异化 | 价格带空位、配置、差评主题、内容空位 | 有明确结构/人群/场景空位 | 只有内容/颜色差异 | 纯同质化标品，只有价格战 |

**任何 hard fail → 不能给 Go。**
**供应链 unknown → 最高只能给 Conditional。**

## 2. 六项评分与权重

| 项 | 权重 | 高分（75+） | 中分（55–74） | 低分（<55） |
| --- | ---: | --- | --- | --- |
| 需求 | 30% | 规模大、增长、季节可控 | 规模大但下滑/波动 | 规模小或持续下滑 |
| 竞争 | 25% | 分散、低评论墙、内容未饱和 | 中等集中、部分壁垒 | 高度集中、Amazon 强势、评论墙高 |
| 经济性 | 25% | margin ≥ 20% | 10–20% | < 10% |
| 差异化 | 10% | 明确空位 | 弱差异 | 同质化 |
| 供应链 | 5% | 已验证 | 部分验证 | 未知 |
| 内容 | 5% | 有内容空位 | 标配 | 严重饱和 |

总分 = Σ(分数 × 权重)，四舍五入。**总分不能覆盖 hard fail。**

## 3. 结论规则

```
if any hard gate == fail:            No-Go
elif supply == unknown:              Conditional（最高）
elif total >= 70 and margin >= 20:   Go
elif total >= 55 and margin >= 10:   Conditional
else:                                No-Go
```

`narrative.hero.verdict` 和 `narrative.total_score` 必须与以上规则一致；`verify_report.py` 至少校验总分。

## 4. 单位经济公式

```text
referral       = price × referral%          # default 15%
ad_per_unit    = CPC ÷ (CVR / 100)
return_cost    = price × return%
contribution   = price − landed − referral − FBA − ad_per_unit − return_cost − overhead
margin         = contribution ÷ price
break_even_acos = (price − landed − referral − FBA − return_cost − overhead) ÷ price
```

必须显式写出：price、landed、FBA、CPC、CVR、return、overhead。
不得把“广告后台 ACOS”与“break-even ACOS”混为一谈。

## 5. 需求判断

- 先看 **成交额/销量同比**，再看 **搜索同比**；两者背离时写清楚，不要只取好看的那个。
- 季节品用**同月对比**或季调；不要用 11 月对 8 月。
- 搜索量 ≠ 销量；关键词只是需求代理。
- 价格带看“销量份额 vs 销售额份额”的差，不只看均价。

## 6. 竞争判断

- TOP3 / CR10 / Amazon 自营 / TOP3 卖家，至少四个数。
- 评论看**分层**：0–50、51–200、201–1000、1001+；每层 ASIN 占比和销量占比。
- 内容看 A+ / 视频 / 品牌店覆盖率；覆盖率 > 80% 视为标配，不再算差异。
- 差评看 Top3 Customers Say 的负面主题和次数，标注“样本”。

## 7. 产品判断

- 价格带空位必须同时看：ASIN 数、销量份额、销售额份额、均价。
- 概念最多 3 个；每个写清：价格、配置、场景、差异、风险。
- 明确写“不做什么”，比只写“做什么”更有用。

## 8. 数据质量

- 官方类目 vs 关键词样本，只能二选一，全文统一口径。
- 第三方估算必须标“Sorftime/SIF 估算，不是 Amazon 官方”。
- 缺失模块写进 `narrative.data.gaps`；不要用 0 或平均值填充。
- 成本假设与实测数据分栏；不要把 landed 当事实。
