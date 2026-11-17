---
name: amazon-category-decision
description: "Use when the user asks whether an Amazon category / niche is worth entering, or asks for a category market + competition + product + unit-economics report. Runs a fixed pipeline: lock the Amazon node (or keyword niche), pull category report + Top100 + keywords + trends + top-product details/reviews from a Sorftime or SIF MCP, normalize to data.json, write narrative.json under a fixed rubric, render a 6-tab HTML report, then verify row counts/totals/scores and data gaps. Do not use for single-ASIN traffic diagnosis, ad-structure audits, or keyword screening only."
---

# Amazon category decision

Turns one Amazon category into a decision-grade HTML report. **Six sections, fixed gates, zero fabricated numbers.**

## When to use / not use

| Use | Don't use |
| --- | --- |
| “这个类目能不能做 / 值不值得进” | 单个 ASIN 流量下跌归因 |
| “出一份类目市场 + 竞争 + 产品 + 单位经济报告” | 广告结构反推 |
| “按这个 Node / 类目做一份可交付 HTML” | 只筛词，不要报告 |

## Non-negotiables

1. **No invented numbers.** Every figure comes from `data.json`. If a module is missing, put it in `gaps`; do not estimate silently.
2. **Lock the node first.** Run `search`; show candidates; ask the user to confirm one. Never guess an ambiguous node.
3. **Two calibres, never mixed:** official category Top100 vs keyword-defined sample. Label the mode in `meta`.
4. **Assumptions are separate.** Landed cost, FBA, CPC, CVR, return rate are inputs — mark them “假设/样本”, never “实测”.
5. **Third-party estimates.** Sorftime/SIF are not Amazon official; put this in the report banner and footer.
6. **No API key in output.** Key only in `.env`; never in HTML, JSON, logs, or commits.
7. **One category, one report.** Don’t mix categories or reuse another category’s narrative.

## Pipeline

### P0 — read the brief and lock scope

Extract:

- site (`US`, `GB`, `DE` …)
- category name or Node
- mode: `category` (official node) or `keyword` (niche; v1.1)
- window (default latest 24 months)
- target price / landed / CPC / CVR / return / FBA (if user has them)
- output language (default Chinese; keep category names in English)

If the user only gives a category name, run:

```bash
python scripts/ecom_skill.py search --provider sorftime --category "<name>"
```

Show `node_id + category_name`; ask for confirmation when more than one candidate. The fetch script refuses ambiguity.

### P1 — doctor

```bash
python scripts/ecom_skill.py doctor --provider sorftime
python scripts/ecom_skill.py doctor --provider sif --list-tools
```

- Sorftime: should pass without edits.
- SIF: if tool mapping is empty, use `--list-tools` and fill `config/providers.json -> sif.tools`; re-run doctor.

### P2 — fetch raw

```bash
python scripts/ecom_skill.py fetch \
  --provider sorftime --slug <slug> --node <node> \
  --category "<category>" --site US
```

This saves every MCP payload under `data/<slug>/raw/`. Do not retype payloads; keep raw for audit.

### P3 — normalize

```bash
python scripts/ecom_skill.py normalize \
  --slug <slug> --category "<category>" --node <node> \
  --price <target> --landed <cost> --cpc <cpc> --cvr <cvr> \
  --return-rate <return> --fba <fba>
```

Outputs `data/<slug>/data.json`:

- `market` (sales/revenue/season, or search for keyword mode)
- `metrics` (YoY, ASP, Top3, CR10, Amazon share, return, peak/trough)
- `priceBands`, `brands`, `review`, `content`
- `products` (Top10)
- `keywords` (8 max)
- `assumptions`

Read the numbers. If `products` is empty or `months` < 12, stop and report the gap.

### P4 — write `narrative.json` (quality lives here)

Use `reference/rubric.md` and `reference/data-contract.md`. Start from `examples/drafting-chair/narrative.json`.

Required keys:

```text
hero, kpis, scores, total_score, gates, overview,
demand, competition, products, concepts, data
```

Rules:

- Each gate: `pass | warn | fail | unknown`, with a data-backed sentence.
- Scores: 0–100; total = weighted sum (tolerance 1 in verify).
- Any `fail` on demand / competition / economics / supply / differentiation → verdict cannot be Go.
- Supply `unknown` → at most Conditional.
- Narrative numbers must match `data.json`; do not recompute in prose.
- Concepts: 3 max; each must state target price, config, and why it is not already saturated.
- Data: 14 slots; mark done/missing; list only missing data in requests.

### P5 — build

```bash
python scripts/ecom_skill.py build --slug <slug>
```

Output: `data/<slug>/report.html`. Fixed template, no build step, no CDN.

### P6 — verify

```bash
python scripts/ecom_skill.py verify --slug <slug>
```

Checks:

- data/products/months/keywords present
- narrative required keys
- gate statuses valid
- total score = weighted score (±1)
- no `__DATA__` / `__NARRATIVE__` / `undefined` / `NaN`
- report size, Amazon product links, coverage tag

Any failure: fix data/narrative, do not hand-edit report.html.

### P7 — deliver

- Report path: `data/<slug>/report.html`
- Raw: `data/<slug>/raw/`
- Data: `data/<slug>/data.json`
- Narrative: `data/<slug>/narrative.json`
- Say explicitly: node, site, window, source, assumptions, gaps.

## Category vs keyword mode

- `category` (v1.0): official Amazon child node. Full pipeline above.
- `keyword` (v1.1): no official node. Use `keyword_detail` + `keyword_search_results`; build a filtered ASIN sample. Do not label it “Top100 category”; label “关键词细分 · N ASIN 样本”.
- If the user gives `criss cross office chair`, confirm whether they mean the exact phrase; do not silently substitute `criss cross chair`.

## Unit economics formula

```text
referral   = price × referral% (default 15%)
ad/unit    = CPC ÷ (CVR/100)
return     = price × return%
contribution = price − landed − referral − FBA − ad − return − overhead
margin     = contribution ÷ price
break-even ACOS = (price − landed − referral − FBA − return − overhead) ÷ price
```

Every output must show the assumptions used. If contribution < 0, the report must say so; don’t hide it in an average.

## Failure rules

- MCP initialize fails → stop, show provider/URL (without key), don’t fabricate.
- Category report empty → stop; don’t build from products alone.
- Product details fail for >3 of top10 → mark content/FBA as gaps; don’t infer.
- Keyword trend missing → `yoy: null`; write “无趋势” in narrative; don’t invent.
- Narrative missing → build refuses; do not auto-generate a fake verdict.
- Verify fails → do not deliver.

## References

- `reference/rubric.md` — gates, weights, verdict rules
- `reference/data-contract.md` — data.json / narrative.json schema
- `reference/sif.md` — SIF tool mapping
- `reference/qa-checklist.md` — pre-delivery checklist
- `examples/drafting-chair/` — golden case (data + narrative + report)
