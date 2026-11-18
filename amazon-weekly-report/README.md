# Amazon 周报 · 里子 + 壳子

给一组 SPU（默认所有启用的），产出一份能直接粘进飞书文档的经营周报：**总览一张表 + 每个 SPU 一段 A/B/C/D**。  
数据：领星（销量/利润/广告）+ SIF 或 Sorftime（关键词/流量/竞品）+ 用户配置（目标/成本）。

## 一分钟看效果

```bat
scripts\run.cmd demo
start examples\weekly-demo\report.html
```

演示 3 个 SPU（含 1 个健康、1 个落后、1 个双父体），会明确标注“演示数据”，不联网。看 `report.html` 右上角「复制到飞书」，全选粘贴即可。

## 结构

```
weekly-report/
├─ SKILL.md                 给模型看的操作规程（首次使用、口径、故障处理）
├─ scripts/
│  ├─ run.cmd / run.ps1     找 Python 并转调 wreport.py（Windows）
│  ├─ wreport.py            CLI：init / targets / doctor / schema / collect / build / run / demo / check
│  └─ wr/
│     ├─ mcp.py             MCP 客户端（Streamable HTTP，header/query 鉴权，SSE）
│     ├─ collect_lingxing.py 领星取数 + 字段别名 + 参数自动匹配
│     ├─ collect_keywords.py SIF 优先，Sorftime 回退（占比估算）
│     ├─ competitor.py      竞品快照 + 变体/价格/评分变化
│     ├─ compute.py         周对比、目标拆分、利润、预警（纯函数）
│     ├─ render.py          多 SPU HTML 壳子 + Markdown 兜底
│     ├─ pipeline.py        按 SPU 建 data.json，再合成周报
│     └─ demo.py            3 SPU 演示数据
├─ config/
│  ├─ products.json         站点/SPU/父体/竞品（一行一个 SPU）
│  ├─ targets.json          每个 SPU 的月目标、目标利润率、成本、核算规则
│  ├─ settings.json         周起始、阈值、关键词源、取整
│  └─ lingxing.json         工具名映射、参数覆盖、字段别名
├─ templates/               预留（当前模板内嵌在 render.py）
└─ examples/weekly-demo/    多 SPU 演示输出（本仓库未附带，跑 demo 后本地生成）
```

## 快速开始

1. **登记产品**

```bat
scripts\run.cmd init --site US --spu YOURSPU --parent B0XXXXXXXX ^
  --competitor https://www.amazon.com/dp/B0XXXXXXXX
```

多个父体就重复 `--parent`。

2. **填目标与成本**：复制 `config/targets.example.json` 为 `config/targets.json` 再填，或用命令：

```bat
scripts\run.cmd targets --spu YOURSPU --monthly 100000 --margin 0.15 ^
  --unit-cost 20 --first-leg 4 --fba 6 --referral 0.15 --other 1
```

```json
"YOURSPU": {
  "monthly": { "2026-01": 100000 },
  "default_monthly": 100000,
  "target_margin": 0.15,
  "cost": { "unit_cost": 20.0, "first_leg": 4.0, "fba_fee": 6.0, "referral_rate": 0.15, "other_per_unit": 1.0 },
  "rules_note": "利润 = 销售额 − 采购 − 头程 − 佣金 − FBA − 广告 − 退款 − 其他"
}
```

> `config/products.json` 和 `config/targets.json` 放的是你自己的真实数据，已在 `.gitignore` 里，不会被提交。首次使用从对应的 `.example.json` 复制一份再改。

3. **填密钥**：复制 `.env.example` 为 `.env`，填 `LINGXING_MCP_KEY` / `SIF_MCP_URL` / `SORFTIME_MCP_KEY`。

4. **跑**

```bat
scripts\run.cmd doctor --provider lingxing
scripts\run.cmd run --product 66D50F
scripts\run.cmd check --product 66D50F
start data\US-66D50F\report.html
```

## 为什么需要“壳子”

飞书文档不支持直接渲染外部 HTML/JS，但支持**富文本粘贴**。所以：

- 页面只用标题、段落、表格，表格单元格带内联样式；粘贴后边框、底色、对齐都在。
- 页面上的大标题、圆角、悬浮按钮只是预览效果；粘进飞书会变成文档原生样式，层级不变。
- 「复制到飞书」按钮用 `ClipboardItem('text/html')`，复制的是富文本，不是截图。

## 数据契约（`data.json`）

```
meta      站点/SPU/周区间/数据源/是否演示
overview  销量、销售额、周目标、达成率、目标/实际利润率
spus[]    metrics(12项+wow)、last、daily、profit、ads{campaigns,keywords,daily}
          parents[]{asin, keywords{organic,ads,top80}}
competitor 基础信息 + 价格/评分/变体变化 + 前80%结构
flags/findings  规则生成的预警与结论
gaps      数据缺口
```

报告只读 `data.json`；要改样式改 `render.py`，要改口径改 `compute.py`。

## 领星适配

不同租户的参数名和返回字段可能不同，脚本做了三层兜底：

1. 工具名在 `config/lingxing.json → tools`（已按官方目录填好）。
2. 参数从实时 schema 自动匹配（`start_date` / `country` / `spu` / `sid` …），可用 `args` 写死。
3. 字段走 `field_aliases`，未识别的列会出现在 `raw/lingxing.json → columns`，加别名即可。

第一次接通跑 `scripts\run.cmd schema`，能看到每个工具的真实参数和必填项。

## 关键词与“流量占比”

- SIF 有真实流量占比时直接使用。
- SIF 不可用（如 401）自动降级 Sorftime：有自然位/广告位/搜索量，但没有占比。报告用
  `搜索量 × 位置权重` 估算，并在标题、表头、脚注三处标注“估算”。
- 竞品同样只取前 80% 流量，不拉长尾。

## 校验

```bat
scripts\run.cmd check --product 66D50F
```

检查：日合计=周合计、达成率=销售额/目标、利润率=利润/销售额、HTML 无 `None/NaN`、六段齐全。

## 限制

- 需要本机有 Python 3.10+；`run.cmd` 会自动找，找不到会提示。
- 不调用飞书 API，交付靠复制粘贴。
- 竞品变化从第二次运行开始有对比。
- 工作台（ecom-workbench）里没有终端，无法直接跑 Python；这条链路目前适合 DSH / 本机终端 / 定时任务。
