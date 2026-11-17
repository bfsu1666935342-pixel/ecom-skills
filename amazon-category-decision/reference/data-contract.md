# 数据契约 · Data Contract

`normalize.py` 产出 `data.json`；`build_report.py` 读取 `data.json + narrative.json`。
不要手改 `report.html`；改数据或判断，再重新 build。

## data.json

```jsonc
{
  "meta": {
    "category": "Drafting Chairs",
    "title": "Drafting Chair",
    "title_cn": "类目分析",
    "site": "US",
    "node": "1069142",
    "mode": "category",              // category | keyword
    "window": "2024-11 — 2026-10",
    "source": "Sorftime MCP",
    "pulled": "2026-11-12",
    "brand_sub": "SORFTIME · V1.0",
    "source_banner": "……",
    "footer": "……",
    "footer_right": "……"
  },

  "market": {
    "mode": "sales",                  // sales | search
    "months": ["2024-11", "..."],
    "sales": [58009, "..."],          // sales mode
    "revenue": [6079923, "..."],      // sales mode
    "search": [19949, "..."],         // search mode only
    "season": [0.89, "..."]           // 12 values
  },

  "metrics": {
    "sales": 27188,
    "revenue": 2968929,
    "yoy": -35.5,
    "asp": 109.2,
    "top100Sales": 27665,
    "top100Revenue": 2892680,
    "cr3": 28.25,
    "cr10": 56.75,
    "amazonShare": 13.37,
    "top3Seller": 31.82,
    "returnRate": 2.93,
    "avgPrice": 109.02,
    "peakTrough": 1.53
  },

  "priceBands": [
    {"name": "<$80", "asins": 32, "unitShare": 37.8, "revShare": 22.9, "avg": 55.68, "role": "低价走量"}
  ],

  "brands": [
    {"name": "Primy", "share": 11.39, "avg": 119.99, "count": 2}
  ],

  "review": {
    "tiers": [
      {"label": "0–50", "asinShare": 32.0, "salesShare": 15.8}
    ],
    "negatives": [
      {"label": "结构 / 稳固", "count": 167}
    ]
  },

  "content": {"aplus": 100, "video": 70, "store": 100, "sample": 10},

  "products": [
    {
      "asin": "B0...",
      "brand": "Primy",
      "title": "...",
      "price": 129.99,
      "monthly_sales_volume": 2895,
      "rating_count": 3542,
      "rating": 4.3,
      "a_plus": true,
      "has_video": true,
      "has_brand_store": true,
      "seller": "Primy-Super",
      "is_fba": true,
      "fba_fee": 27.41,
      "online_date": "2022-08-04",
      "features": "加高 · 翻扶手 · 脚托"
    }
  ],

  "keywords": [
    {
      "term": "drafting chair",
      "volume": 99649,
      "yoy": 7.9,
      "cpc": 3.88,
      "conv": 4.28,
      "top3Click": 30.55,
      "lowReview": 35.71,
      "verdict": "增长"
    }
  ],

  "assumptions": {
    "price": 129,
    "landed": 45,
    "cpc": 3.88,
    "cvr": 4.28,
    "ret": 2.93,
    "fba": 35,
    "referral": 15,
    "overhead": 6
  }
}
```

## narrative.json

```jsonc
{
  "hero": {
    "eyebrow": "AMAZON US · ...",
    "title": "Drafting Chair",
    "title_cn": "类目分析",
    "subtitle": "……",
    "tags": ["SORFTIME MCP · 实拉", "..."],
    "verdict": "暂不进入",
    "verdict_class": "red",          // red | amber | green
    "score": 40,
    "reason": "……",
    "mini": [{"label": "需求", "value": "35"}]
  },

  "kpis": [
    {"label": "2026-10 销量", "value": "27,188", "unit": "件", "sub": "Top100 · 自然月"}
  ],

  "scores": {
    "demand": 35, "competition": 65, "economics": 10,
    "differentiation": 55, "supply": 45, "content": 55
  },
  "total_score": 40,
  "score_note": "……",

  "gates": [
    {"label": "需求", "status": "fail", "text": "……"}
  ],

  "overview": {
    "signals": ["..."], "risks": ["..."], "next": ["..."]
  },

  "demand": {
    "subtitle": "……",
    "season_subtitle": "……",
    "insight": "……",
    "season_insight": "……",
    "keyword_tag": "4 词 · 实测",
    "keyword_note": "……"
  },

  "competition": {
    "band_insight": "……",
    "brand_top": "……",
    "brand_note": "……",
    "metrics": [{"label": "Amazon 自营份额", "value": "13.4%"}],
    "review_note": "……",
    "content_callout": "……"
  },

  "products": {
    "note_top": "……",
    "note": "……",
    "gaps": ["..."],
    "positioning_good": "……",
    "positioning_bad": "……"
  },

  "concepts": [
    {
      "key": "A", "name": "Tall Executive 199", "price": "$199–249",
      "rec": false, "bullets": ["..."], "note": "……"
    }
  ],

  "economics": {"ladder_note": "……"},

  "data": {
    "coverage": "10 / 14",
    "gaps": [{"done": true, "text": "类目 24 个月销量 / 销售额"}],
    "requests": [{"priority": "P0", "title": "供应商报价", "desc": "……", "level": "必须"}],
    "limits": [{"title": "数据层", "text": "……"}]
  }
}
```

## 校验规则

`verify_report.py` 会检查：

- `data.products` / `data.market.months` / `data.keywords` 非空
- `narrative` 必需键齐全
- gate status 合法
- `total_score` 与加权分误差 ≤ 1
- HTML 中没有 `__DATA__` / `__NARRATIVE__` / `undefined` / `NaN`
- report 大小与 Amazon 商品链接存在
- `data.coverage` 存在
