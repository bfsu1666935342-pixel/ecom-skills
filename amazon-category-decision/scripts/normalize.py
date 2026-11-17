"""Normalize raw MCP payloads into the skill's canonical data.json.

Raw files expected (all under --input):
  category_report.json      category_report result
  products.json             category_products list (Top100)
  keywords.json             category_keywords list (40)
  keyword_details.json      {term: keyword_detail data}
  keyword_trends.json       {term: keyword_trend data}
  trends.json               {SalesCount: ..., AvgPrice: ..., ...}
  product_details.json      {asin: product_detail data}
  customers_say.json        {asin: product_customers_say data}
  product_content.json      {asin: product_content data}

This module is deliberately deterministic. Judgement belongs in narrative.json,
not here.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_pairs(arr: Iterable[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in arr or []:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            try:
                out[k] = float(v)
            except ValueError:
                continue
    return out


def parse_alt_pairs(arr: Iterable[Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    arr = list(arr or [])
    for i in range(0, len(arr) - 1, 2):
        try:
            out[str(arr[i])] = float(arr[i + 1])
        except (TypeError, ValueError):
            continue
    return out


def top3_click(detail: Dict[str, Any]) -> Optional[float]:
    vals = []
    for item in detail.get("top3_asin") or []:
        try:
            vals.append(float(str(item).split(",")[1].replace("%", "")))
        except (IndexError, ValueError):
            continue
    return round(sum(vals), 2) if vals else None


def low_review(detail: Dict[str, Any]) -> Optional[float]:
    stats = detail.get("search_result_first_page_stats") or {}
    raw = stats.get("organic_low_review_ratio") or ""
    if "|" in raw:
        raw = raw.split("|")[0]
    try:
        return float(raw)
    except ValueError:
        return None


def feature_string(product: Dict[str, Any]) -> str:
    text = ((product.get("title") or "") + " " + (product.get("sub_title") or "")).lower()
    tags: List[str] = []
    pairs = [
        ("big and tall", "Big & Tall"),
        ("wide", "宽座"),
        ("flip", "翻扶手"),
        ("foot rest", "脚托"),
        ("footrest", "脚托"),
        ("no wheel", "无轮"),
        ("wheel", "带轮"),
        ("armless", "无扶手"),
        ("mesh", "Mesh"),
        ("fabric", "Fabric"),
        ("leather", "PU/皮"),
        ("standing", "站立桌"),
        ("tall", "加高"),
        ("drafting", "Drafting"),
    ]
    for needle, label in pairs:
        if needle in text and label not in tags:
            tags.append(label)
    return " · ".join(tags[:4]) if tags else "—"


def quartile_bands(products: List[Dict[str, Any]], total_sales: int, total_rev: float) -> List[Dict[str, Any]]:
    prices = sorted(float(p["price"]) for p in products if float(p.get("price") or 0) > 0)
    if not prices:
        return []
    q = statistics.quantiles(prices, n=4)
    cuts = [min(prices), q[0], q[1], q[2], max(prices) + 0.01]
    names = [f"<${cuts[1]:.0f}", f"${cuts[1]:.0f}–{cuts[2]:.0f}", f"${cuts[2]:.0f}–{cuts[3]:.0f}", f">${cuts[3]:.0f}"]
    bands = []
    for i, name in enumerate(names):
        lo, hi = cuts[i], cuts[i + 1]
        group = [p for p in products if lo <= float(p["price"]) < hi]
        sales = sum(int(p.get("monthly_sales_volume") or 0) for p in group)
        rev = sum(int(p.get("monthly_sales_volume") or 0) * float(p.get("price") or 0) for p in group)
        bands.append({
            "name": name,
            "asins": len(group),
            "unitShare": round(sales / total_sales * 100, 1) if total_sales else 0,
            "revShare": round(rev / total_rev * 100, 1) if total_rev else 0,
            "avg": round(statistics.mean([float(p["price"]) for p in group]), 2) if group else 0,
            "role": "",
        })
    # label role by revenue share, not by hand
    for b in bands:
        b["role"] = "收入核心" if b["revShare"] == max(x["revShare"] for x in bands) else ("低价走量" if b["avg"] == min(x["avg"] for x in bands) else "过渡")
    return bands


def normalize(raw_dir: Path, out_path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    report = read_json(raw_dir / "category_report.json", {})
    products = read_json(raw_dir / "products.json", []) or []
    keywords_raw = read_json(raw_dir / "keywords.json", []) or []
    keyword_details = read_json(raw_dir / "keyword_details.json", {}) or {}
    keyword_trends = read_json(raw_dir / "keyword_trends.json", {}) or {}
    trends = read_json(raw_dir / "trends.json", {}) or {}
    details = read_json(raw_dir / "product_details.json", {}) or {}
    says = read_json(raw_dir / "customers_say.json", {}) or {}

    # market trend: use monthly pairs, drop clearly partial last month
    sales_pairs = parse_pairs(trends.get("SalesCount") or [])
    price_pairs = parse_pairs(trends.get("AvgPrice") or [])
    months = sorted(sales_pairs)
    if len(months) >= 2 and sales_pairs[months[-1]] < sales_pairs[months[-2]] * 0.5:
        months = months[:-1]
    months = months[-24:]
    sales = [int(sales_pairs[m]) for m in months]
    prices = [price_pairs.get(m, 0.0) for m in months]
    revenue = [round(sales[i] * prices[i], 2) for i in range(len(months))]
    by_month: Dict[int, List[int]] = defaultdict(list)
    for m, s in zip(months, sales):
        by_month[int(m[5:7])].append(s)
    mean = statistics.mean([statistics.mean(v) for v in by_month.values()]) if by_month else 1
    season = [round(statistics.mean(by_month[i]) / mean, 4) if by_month.get(i) else 0 for i in range(1, 13)]
    peak = max(season) if season else 0
    trough = min([x for x in season if x > 0], default=1)
    peak_trough = round(peak / trough, 2) if trough else 0
    yoy = round((sales[-1] / sales[-13] - 1) * 100, 1) if len(sales) >= 13 and sales[-13] else 0

    # products
    total_sales = sum(int(p.get("monthly_sales_volume") or 0) for p in products) or 1
    total_rev = sum(int(p.get("monthly_sales_volume") or 0) * float(p.get("price") or 0) for p in products) or 1
    for p in products:
        d = details.get(p.get("asin")) or {}
        if d:
            p.update({
                "monthly_sales_volume": d.get("monthly_sales_volume", p.get("monthly_sales_volume")),
                "monthly_sales_amount": d.get("monthly_sales_amount", p.get("monthly_sales_amount")),
                "rating": d.get("star_rating", p.get("ratings")),
                "rating_count": d.get("review_count", p.get("rating_count")),
                "a_plus": d.get("a_plus"),
                "has_video": d.get("has_video"),
                "has_brand_store": d.get("has_brand_store"),
                "is_fba": d.get("is_fba"),
                "fba_fee": d.get("fba_fee"),
                "seller": d.get("seller_name", p.get("buybox_seller")),
                "online_date": d.get("online_date"),
                "variations": d.get("variation_count"),
            })
        p["features"] = feature_string(p)
    products.sort(key=lambda x: int(x.get("monthly_sales_volume") or 0), reverse=True)
    top = products[:10]

    # brands
    brand_acc: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"sales": 0, "prices": [], "count": 0})
    for p in products:
        b = p.get("brand") or "—"
        brand_acc[b]["sales"] += int(p.get("monthly_sales_volume") or 0)
        brand_acc[b]["prices"].append(float(p.get("price") or 0))
        brand_acc[b]["count"] += 1
    brands = []
    for name, v in brand_acc.items():
        brands.append({"name": name, "share": round(v["sales"] / total_sales * 100, 2), "avg": round(statistics.mean(v["prices"]), 2) if v["prices"] else 0, "count": v["count"]})
    brands.sort(key=lambda x: x["share"], reverse=True)

    # price bands
    bands = quartile_bands(products, total_sales, total_rev)

    # review tiers
    tiers = []
    for name, lo, hi in [("0–50", 0, 50), ("51–200", 50, 200), ("201–1000", 200, 1000), ("1001+", 1000, 10**9)]:
        group = [p for p in products if lo <= int(p.get("rating_count") or 0) < hi]
        tiers.append({"label": name, "asinShare": round(len(group) / max(len(products), 1) * 100, 1), "salesShare": round(sum(int(p.get("monthly_sales_volume") or 0) for p in group) / total_sales * 100, 1)})

    # content top10
    content = {
        "aplus": round(sum(1 for p in top if p.get("a_plus")) / max(len(top), 1) * 100),
        "video": round(sum(1 for p in top if p.get("has_video")) / max(len(top), 1) * 100),
        "store": round(sum(1 for p in top if p.get("has_brand_store")) / max(len(top), 1) * 100),
        "sample": len(top),
    }

    # negatives from top3 customers_say
    neg: Dict[str, Dict[str, int]] = defaultdict(lambda: {"neg": 0})
    for asin in list(says)[:3]:
        d = says[asin] or {}
        if not isinstance(d, dict):
            # Providers return a bare string such as "No relevant data." for ASINs without a review summary.
            continue
        for row in d.get("details") or []:
            if not isinstance(row, dict):
                continue
            neg[row.get("keyword") or "other"]["neg"] += int(row.get("negative") or 0)
    negatives = [{"label": k, "count": v["neg"]} for k, v in sorted(neg.items(), key=lambda x: -x[1]["neg"]) if v["neg"] > 0][:6]

    # keyword snapshot + details
    keywords = []
    for k in keywords_raw[:40]:
        term = k.get("keyword") or ""
        d = keyword_details.get(term) or {}
        tr = keyword_trends.get(term) or {}
        sv = parse_alt_pairs(tr.get("search_volume_trend") or [])
        yoy_k = round((sv.get("202610", 0) / sv.get("202510", 1) - 1) * 100, 1) if sv.get("202510") else None
        keywords.append({
            "term": term,
            "volume": int(float(k.get("monthly_search_volume") or 0)),
            "yoy": yoy_k,
            "cpc": float(k.get("cpc_exact_bid") or 0),
            "conv": float(d.get("search_conversion_rate_90d") or 0) if d else 0,
            "top3Click": top3_click(d) if d else None,
            "lowReview": low_review(d) if d else None,
            "verdict": "增长" if (yoy_k or 0) >= 5 else ("下滑" if (yoy_k or 0) < 0 else "观察"),
        })
    tokens = [t.rstrip("s") for t in __import__("re").split(r"[^a-z0-9]+", (args.category or "").lower()) if len(t) > 2]
    def keyword_relevance(term: str) -> int:
        return sum(1 for t in tokens if t and t in term.lower())
    keywords.sort(key=lambda x: (keyword_relevance(x["term"]), x["volume"]), reverse=True)
    keywords = keywords[:8]

    # assumptions: user overrides, otherwise data-derived
    median_price = statistics.median([float(p.get("price") or 0) for p in top]) if top else 0
    cpc_default = keywords[0]["cpc"] if keywords else 1.0
    cvr_default = keywords[0]["conv"] if keywords and keywords[0]["conv"] else 5.0
    fba_default = statistics.median([float(p.get("fba_fee") or 0) for p in top if float(p.get("fba_fee") or 0) > 0] or [35.0])
    assumptions = {
        "price": args.price if args.price is not None else round(median_price, 2),
        "landed": args.landed if args.landed is not None else round(median_price * 0.4, 2),
        "cpc": args.cpc if args.cpc is not None else round(cpc_default, 2),
        "cvr": args.cvr if args.cvr is not None else round(cvr_default, 2),
        "ret": args.return_rate if args.return_rate is not None else float(report.get("return_rate") or 0),
        "fba": args.fba if args.fba is not None else round(fba_default, 2),
        "referral": 15,
        "overhead": 6,
    }

    meta = {
        "category": args.category or report.get("category_name") or args.slug,
        "title": args.title or args.category or args.slug,
        "title_cn": "类目分析",
        "site": args.site,
        "node": str(args.node or report.get("node_id") or ""),
        "mode": "category",
        "window": f"{months[0]} — {months[-1]}" if months else "",
        "source": "Sorftime MCP" if args.provider == "sorftime" else "SIF MCP",
        "pulled": args.pulled,
        "brand_sub": f"{args.provider.upper()} · V1.0",
        "source_banner": f"{args.provider.upper()} MCP 实拉 {args.pulled} · Amazon {args.site} · {args.category or args.slug} · 第三方估算，不是 Amazon 官方。",
        "footer": f"CATEGORY LAB · {args.category or args.slug} · {args.pulled} · 第三方估算，非 Amazon 官方",
        "footer_right": "输入变化会重算经济性与评分 · 数据仅保存在本页内存 · 不构成投资建议",
    }

    data = {
        "meta": meta,
        "market": {"mode": "sales", "months": months, "sales": sales, "revenue": revenue, "season": season},
        "metrics": {
            "sales": sales[-1] if sales else 0,
            "revenue": revenue[-1] if revenue else 0,
            "yoy": yoy,
            "asp": round(revenue[-1] / sales[-1], 2) if sales and sales[-1] else 0,
            "top100Sales": int(report.get("top100_monthly_sales_volume") or 0),
            "top100Revenue": round(float(report.get("top100_monthly_sales_amount") or 0), 2),
            "cr3": float(report.get("top3_product_sales_volume_share") or 0),
            "cr10": round(sum(b["share"] for b in brands[:10]), 2),
            "amazonShare": float(report.get("amazon_owned_sales_volume_share") or 0),
            "top3Seller": float(report.get("top3_seller_sales_volume_share") or 0),
            "returnRate": float(report.get("return_rate") or 0),
            "avgPrice": float((report.get("category_products_price") or [0])[0]),
            "peakTrough": peak_trough,
        },
        "priceBands": bands,
        "brands": brands[:10],
        "review": {"tiers": tiers, "negatives": negatives},
        "content": content,
        "products": [
            {
                "asin": p.get("asin"), "brand": p.get("brand"), "title": p.get("title"), "price": float(p.get("price") or 0),
                "monthly_sales_volume": int(p.get("monthly_sales_volume") or 0), "rating_count": int(p.get("rating_count") or 0),
                "rating": float(p.get("rating") or 0), "a_plus": bool(p.get("a_plus")), "has_video": bool(p.get("has_video")),
                "has_brand_store": bool(p.get("has_brand_store")), "seller": p.get("seller") or p.get("buybox_seller") or "—",
                "is_fba": p.get("is_fba"), "fba_fee": float(p.get("fba_fee") or 0), "online_date": p.get("online_date") or "—",
                "features": p.get("features") or "—",
            }
            for p in top
        ],
        "keywords": keywords,
        "assumptions": assumptions,
        "gaps": [],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", default="sorftime")
    parser.add_argument("--site", default="US")
    parser.add_argument("--category", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--node", default="")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--pulled", default="")
    parser.add_argument("--price", type=float)
    parser.add_argument("--landed", type=float)
    parser.add_argument("--cpc", type=float)
    parser.add_argument("--cvr", type=float)
    parser.add_argument("--return-rate", dest="return_rate", type=float)
    parser.add_argument("--fba", type=float)
    args = parser.parse_args()
    normalize(Path(args.input), Path(args.out), args)


if __name__ == "__main__":
    main()
