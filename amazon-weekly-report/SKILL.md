---
name: amazon-weekly-report
description: "Use when the user asks for an Amazon weekly operating report covering one or more SPUs — sales vs target, profit vs target, ad breakdown, keyword natural/ad positions, and a benchmark competitor — delivered as a Feishu-ready document. Runs a fixed pipeline: collect Lingxing (sales/profit/ads) per SPU, collect SIF or Sorftime (keyword/traffic structure) per parent ASIN, snapshot each competitor, compute week-over-week metrics, then render one multi-SPU HTML with an overview table and an A/B/C/D block per SPU. Use for recurring operating reviews, not for category selection or one-off ASIN diagnosis."
---

# Amazon 周报（多 SPU 经营复盘）

把「这一周所有在跑的 SPU」做成一份**能直接粘进飞书文档**的周报：总览一张表，下面每个 SPU 一段 A/B/C/D。里子是脚本（取数、计算、校验），壳子是 HTML。

## 何时用 / 不用

| 用 | 不用 |
| --- | --- |
| “出一份上周周报，美国站所有 SPU” | “这个类目值不值得做”（用 amazon-category-decision） |
| “66D50F 上周怎么样” | 只查一个 ASIN 为什么跌（用流量诊断） |
| 每周/每月重复的经营复盘 | 临时查一个关键词的搜索量 |

## 硬规则

1. **默认多 SPU。** 周报的主体是“本周所有启用的 SPU”：总览汇总 + 每个 SPU 独立 A/B/C/D；只做单个 SPU 才用 `--product`。
2. **不编数字。** 所有数字来自各自的 `data.json`，`data.json` 只来自领星/SIF/Sorftime 原始响应或用户给的配置。取不到就写进“数据缺口”，不估算、不用记忆补。
3. **父体规则。** 一个 SPU 可能有多个父体 ASIN：整体与广告按 SPU 合并，关键词每个父体单独展开，一段都不省。
4. **周口径固定。** 自然周（周一至周日），默认“上一整周”；`--week` 给周内任意一天。跨月目标按自然日拆分。
5. **目标与成本来自用户。** 月销售目标、目标利润率、产品成本、利润核算规则只从用户/飞书文档来，不猜；缺了就标注“目标缺失/成本缺失”。
6. **key 只进 `.env`。** 不写进 HTML、JSON、日志、聊天回复；不提交。
7. **先校验再交付。** `check` 不过，不发给用户。

## 首次使用（只做一次）

先问用户这五样，缺一不可：

1. **站点**：US / DE / GB / JP …
2. **SPU 清单**：领星里的 SPU 编码，例如 `66D50F`、`71B22A`；周报默认覆盖所有启用的 SPU
3. **每个 SPU 的父体 ASIN**：一个或多个，例如 `B0XXXXXXXX`；明确“多个父体会分别展开关键词”
4. **每个 SPU 的对标竞品链接**：一个 Amazon 链接（或 ASIN）
5. **飞书文档里的经营参数**：每个 SPU 的本月销售额目标、目标利润率、产品成本（采购/头程/FBA/佣金/其他）、利润核算规则

**怎么登记：让用户点技能里的「配置产品」**（工作表格式的表格，一行一个 SPU，可增删改）。
你没有写盘权限时，用 `update_skill_config` 提交改动、让用户点「应用」，**不要让他手改 JSON、也不要让他敲命令行**。

- 多个父体就在同一个 SPU 下加多行。
- 目标与成本在同一个编辑框里填；**没有就留空**，报告会显示缺口，不要填假数。
- **密钥不用单独填**：工作台会把你「数据源」里配好的 MCP 凭据（领星 / SIF / Sorftime）直接注入脚本进程，优先级高于本技能的 `.env`。所以只要在界面里配过一次数据源，换台电脑也不用再填 `.env`。`.env` 只是没配数据源时的兜底。

> 命令行等价操作（仅当用户主动问起、或面板不可用时才提）：
>
> ```bat
> scripts\run.cmd init --site US --spu 66D50F --parent B0XXXXXXXX --competitor https://www.amazon.com/dp/B0XXXXXXXX
> scripts\run.cmd targets --spu 66D50F --monthly 100000 --margin 0.16 --unit-cost 17 --first-leg 3.8 --fba 7 --referral 0.15 --other 1
> ```

  - 领星：`LINGXING_MCP_KEY`（请求头 `X-Mcp-Key`）
  - SIF：`SIF_MCP_URL`（通常已带 `secret-key`）
  - Sorftime：`SORFTIME_MCP_KEY`

连通性检查：

```bat
scripts\run.cmd doctor --provider lingxing
scripts\run.cmd doctor --provider sif
scripts\run.cmd doctor --provider sorftime
```

领星第一次接通后，把真实参数固化下来（不同租户参数名可能不同）：

```bat
scripts\run.cmd schema
```

会写 `config/lingxing.schema.json`，并打印每个工具的参数/必填项。若自动匹配不对，在 `config/lingxing.json` 的 `args` 里写死，例如：

```json
"args": { "performance": { "start_date": "${start}", "end_date": "${end}", "country": "${site}", "spu": "${spu}", "page_size": 200 } }
```

## 数据源与工具

| 内容 | 来源 | 工具 |
| --- | --- | --- |
| 销量、销售额、会话、点击、曝光、订单、退货、退款 | 领星 | `query_product_performance_asin_lists`（按 parent_asin 查，SPU 行没有会话） |
| 广告活动：预算/花费/点击/订单/销售额 | 领星 | `ad_campaign_report`（按活动名包含 SPU 过滤） |
| 关键词花费（跨活动） | 领星 | `ad_campaign_keyword_report`（campaign_id 列表） |
| 利润（有则优先） | 领星 | 产品表现里的 `gross_profit`（已并入 A） |
| 自然位、广告位、流量占比、搜索量 | SIF（优先） | `market_get_asin_keyword_signals`（week 传周日，T+1） |
| 同上（SIF 不可用时） | Sorftime | `product_traffic_terms`（无流量占比，报告标注“估算”） |
| 竞品基础信息 | Sorftime | `product_detail`、`product_variations` |

**领星网关**：这套 MCP 暴露的是 `help → search → action` 四个工具（不是 300 个直连工具）。`collect_lingxing` 已自动识别：`help` 找 toolId，`search` 取参数 schema，`action` 执行。

**已用真实数据验证（2026-11-18）**：
- 领星产品表现按 `parent_asin` + `search_value=[ASIN]` + `sids`（站点店铺）能取到日粒度；SPU 汇总行的 `sessions_total` 是 0，不能用来算会话/CVR。
- `ad_campaign_report` 的 `asin` 过滤对父 ASIN 无效，用活动名包含 SPU 后缀过滤；跨 SPU 共用活动是活动全量花费，和 B① 的 SPU 花费会有差额（报告已注明）。
- SIF `market_get_asin_keyword_signals` 一次最多 300 词，400 词要翻页；`organic_rank`/`sp_rank` 形如 `p1,4/12`，`sb_rank`/`sbv_rank` 是 `sb,1,top`。

**SIF 401 的处理**：自动降级到 Sorftime，并在报告标题和脚注写明“数据源 Sorftime，流量占比为估算”。不要因此卡住整份报告；同时在回复里告诉用户 SIF key 失效。

## 每周运行

```bat
:: 1. 抓数（所有启用 SPU；每个 SPU 本周+上周、关键词、竞品）
scripts\run.cmd run

:: 只跑某一个
scripts\run.cmd run --product 66D50F  # 只跑一个 SPU（界面上已收起，需要时用命令行）

:: 2. 校验（所有 SPU）
scripts\run.cmd check

:: 3. 打开（多 SPU 固定输出到 data/weekly/<周一>/）
start data\weekly\2026-11-09\report.html
```

- 默认周：上一整周。补跑指定周：`--week 2026-11-09`。
- 只重建、不抓数：`scripts\run.cmd build`。
- 只补某一块：`--only performance,campaign`；跳过关键词：`--no-keywords`；强制走 Sorftime：`--keyword-source sorftime`。
- 单个 SPU 时报告仍写到 `data/US-66D50F/report.html`；多 SPU 写到 `data/weekly/<周一>/report.html`。
- 交付：浏览器打开 `report.html` → 右上角「复制到飞书」→ 飞书文档粘贴。表格、标题层级、加粗会保留；屏幕上的圆角/阴影是壳子样式，飞书里会变成文档原生样式，这是预期。
- 存档：每个 SPU 的 `data/US-<SPU>/` 保留 `raw/`、`data.json`、`history/`（竞品上次快照）；周报汇总在 `data/weekly/<周一>/`。

**长度提醒**：3 个 SPU 的完整版约 2 万像素高（约 25–30 页）。SPU 多时，优先保证总览和异常 SPU 的 A/B；C 段关键词是全量，天然占篇幅。若用户要“短”，把 `config/settings.json → thresholds.max_kw_rows` 调小，或只展开异常 SPU。

## 指标口径

| 指标 | 公式 |
| --- | --- |
| 日销（件） | 周销量 ÷ 7 |
| 客单价 | 销售额 ÷ 订单量 |
| 日均总会话 | 会话数 ÷ 7 |
| 日均点击 | 点击量 ÷ 7 |
| 日均 CTR | 点击量 ÷ 曝光量 |
| 广告 CVR | 广告订单 ÷ 广告点击 |
| 整体 CVR | 订单量 ÷ 会话数 |
| CPC | 广告花费 ÷ 广告点击 |
| ACoAS | 广告花费 ÷ 总销售额（分母是全部销售额，看整体健康度） |
| ACOS | 广告花费 ÷ 广告销售额（分母只有广告带来的销售额，看广告效率） |
| 广告订单占比 | 广告订单 ÷ 总订单 |
| 退货率 | 退货量 ÷ 销量 |
| 退款率 | 退款金额 ÷ 销售额 |
| 利润率 | 利润 ÷ 销售额 |

**注意**：领星不同报表里「点击量」可能指总点击或广告点击。报告按“点击 ÷ 曝光”计算 CTR；若贵店口径是广告点击，以 B 段广告点击为准，A 段 CTR 仅作趋势参考。首次接入时用一周真实数据核对一次。

## 目标拆分

```
周目标 = Σ(当月月目标 ÷ 当月天数)，按该周 7 个自然日逐日累加
```

- `weekly_overrides` 可按周一日期覆盖。
- 结果四舍五入到 `target_rounding`（默认 100）。
- 达成率 = 销售额 ÷ 周目标；目标利润率与实际利润率并列展示。

## 利润核算

优先用领星利润（`source=lingxing`）。没有时按配置核算：

```
利润 = 销售额 − 采购成本 − 头程 − 佣金(销售额×费率) − FBA配送费 − 广告费 − 退款 − 其他
利润率 = 利润 ÷ 销售额
```

报告会展开每一项金额和占销售额比例；`rules_note` 会原样出现在脚注。成本为空就写“无法核算”，不填 0 冒充。

## 输出

```
data/US-66D50F/              每个 SPU 一份原始快照
├─ raw/lingxing.json          领星本周/上周、活动、关键词、利润
├─ raw/keywords-<ASIN>.json   每个父体的关键词结构
├─ raw/competitor-<ASIN>.json 竞品快照
├─ history/competitor-*.json  上次快照（算价格/评分/变体变化）
└─ data.json                  该 SPU 的唯一数据源

data/weekly/2026-11-09/      多 SPU 汇总
├─ data.json                  { products: [...], overview: [...], findings: [...] }
├─ report.html                壳子（复制到飞书）
└─ report.md                  纯文本兜底
```

## 故障处理

| 现象 | 处理 |
| --- | --- |
| 领星 401 / 403 | 检查 `X-Mcp-Key` 是否完整、是否误加 `Bearer`；重新复制密钥 |
| 领星工具找不到 | `doctor --provider lingxing --list-tools`，改 `config/lingxing.json → tools` |
| 领星返回 0 行 | 确认 SPU/站点/日期；开 `--only performance` 单独试；看 `raw/lingxing/*.args.json` 实际传参 |
| 字段全 0 | 看 `raw/lingxing.json → columns`，把真实字段名加进 `config/lingxing.json → field_aliases` |
| SIF 401 | 换 key；或允许降级 Sorftime（报告会标注估算） |
| 某 ASIN 无流量词 | Sorftime 对新品/冷门品可能无数据；C 段写缺口，不编词 |
| 上周数据缺失 | 报告显示“上周数据缺失”，变化列不对比；检查上周日期是否跨月/跨年 |
| `check` 失败 | 先修数据，不要手改 report.html |

## 验收清单

- [ ] 总览：所有 SPU 一行，销量、销售额、周目标、达成率、目标/实际利润率齐全；多 SPU 有合计行
- [ ] 本周结论：先给整体（合计销售额/目标、几个达成/落后/利润承压），再每个 SPU 1–2 条
- [ ] 每个 SPU：A 12 项周对比 + 利润核算；B 广告 SPU 总览 + 按父体拆分/每日/活动/关键词花费；C 每个父体 ①自然位 ②广告位 ③前 80%；D 竞品基础信息 + 前 80% 结构
- [ ] 报告里没有 `None` / `NaN` / 占位符
- [ ] 交付时说明：数据源、周区间、估算项、缺口

## 已知限制

- Sorftime 无「流量占比」字段，降级时占比是 `搜索量 × 位置权重` 的估算，只用于排序和结构判断。
- 领星参数/字段因租户而异，第一次接入需要 `schema` + 一次核对。
- 飞书文档是"复制粘贴"交付，不调用飞书 API；不需要飞书应用权限。
- 竞品变体变化从第二次运行开始才有对比（第一次为“首次”）。
