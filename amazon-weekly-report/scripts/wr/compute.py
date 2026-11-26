"""Deterministic computation: week split, WoW metrics, targets, profit, flags."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from .util import days_in_month, num, pct, pp, safe_div, week_days, week_monday

METRICS: List[Tuple[str, str, str]] = [
    ("日销（件）", "units_per_day", "num"),
    ("客单价", "aov", "money"),
    ("日均总会话", "sessions_per_day", "num"),
    ("日均点击", "clicks_per_day", "num"),
    ("日均 CTR", "ctr", "pct2"),
    ("广告 CVR", "ad_cvr", "pct2"),
    ("整体 CVR", "cvr", "pct2"),
    ("CPC", "cpc", "money2"),
    ("ACoAS", "acoas", "pct2"),
    ("广告订单占比", "ad_order_share", "pct"),
    ("退货率", "return_rate", "pct2"),
    ("退款率", "refund_rate", "pct2"),
]


def _sum_daily(daily: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = ("units", "revenue", "sessions", "clicks", "impressions", "orders", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")
    return {key: sum(num(day.get(key)) for day in daily) for key in keys}


def _block_metrics(block: Dict[str, Any]) -> Dict[str, float]:
    aggregate = {k: num(v) for k, v in (block.get("aggregate") or {}).items() if v is not None}
    if not aggregate and block.get("daily"):
        aggregate = _sum_daily(block["daily"])
    if not aggregate:
        aggregate = {key: 0.0 for key in ("units", "revenue", "sessions", "clicks", "impressions", "orders", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")}
    return aggregate


def derived(raw: Dict[str, float]) -> Dict[str, float]:
    units = raw.get("units", 0)
    revenue = raw.get("revenue", 0)
    sessions = raw.get("sessions", 0)
    clicks = raw.get("clicks", 0)
    impressions = raw.get("impressions", 0)
    orders = raw.get("orders", 0)
    ad_clicks = raw.get("ad_clicks", 0)
    ad_spend = raw.get("ad_spend", 0)
    ad_orders = raw.get("ad_orders", 0)
    ad_sales = raw.get("ad_sales", 0)
    return {
        "units": units,
        "revenue": revenue,
        "orders": orders,
        "impressions": impressions,
        "units_per_day": units / 7,
        "aov": safe_div(revenue, orders),
        "sessions_per_day": sessions / 7,
        "clicks_per_day": clicks / 7,
        "ctr": safe_div(clicks, impressions) if impressions else None,
        "cvr": safe_div(orders, sessions),
        "ad_cvr": safe_div(ad_orders, ad_clicks),
        "cpc": safe_div(ad_spend, ad_clicks),
        "acoas": safe_div(ad_spend, revenue),
        "acos": safe_div(ad_spend, ad_sales),
        "ad_order_share": safe_div(ad_orders, orders),
        "return_rate": safe_div(raw.get("returns", 0), units),
        "refund_rate": safe_div(raw.get("refunds", 0), revenue),
        "ad_impressions": raw.get("ad_impressions", 0),
        "ad_clicks": ad_clicks,
        "ad_spend": ad_spend,
        "ad_orders": ad_orders,
        "ad_units": raw.get("ad_units") or ad_orders,
        "ad_units_fallback": not raw.get("ad_units"),
        "ad_sales": ad_sales,
        "ad_ctr": safe_div(ad_clicks, raw.get("ad_impressions", 0)),
        "cpa": safe_div(ad_spend, ad_orders),
        "sessions": sessions,
        "clicks": clicks,
        "returns": raw.get("returns", 0),
        "refunds": raw.get("refunds", 0),
        "profit_lingxing": raw.get("profit", 0),
    }


def weekly_target(entry: Dict[str, Any], monday: dt.date) -> Optional[float]:
    overrides = entry.get("weekly_overrides") or {}
    if monday.isoformat() in overrides:
        return num(overrides[monday.isoformat()])
    monthly = entry.get("monthly") or {}
    default = entry.get("default_monthly")
    if not monthly and default is None:
        return None
    total = 0.0
    for day in week_days(monday):
        month_key = f"{day.year}-{day.month:02d}"
        target = monthly.get(month_key, default)
        if target is None:
            return None
        total += num(target) / days_in_month(day.year, day.month)
    return total


def profit_block(entry: Dict[str, Any], raw: Dict[str, float], revenue: float, units: float, ad_spend: float, refunds: float) -> Dict[str, Any]:
    lingxing_profit = num(raw.get("profit"))
    target_rate = entry.get("target_margin")
    if lingxing_profit:
        return {
            "amount": lingxing_profit,
            "rate": safe_div(lingxing_profit, revenue),
            "target_rate": target_rate,
            "source": "lingxing",
            "note": "利润取自领星利润报表（get_profit_report_msku / 产品表现），按其口径。",
        }
    cost = entry.get("cost") or {}
    if not cost:
        return {"amount": None, "rate": None, "target_rate": target_rate, "source": "missing", "note": "缺成本配置，无法核算利润。"}
    unit_cost = num(cost.get("unit_cost"))
    first_leg = num(cost.get("first_leg"))
    fba_fee = num(cost.get("fba_fee"))
    referral_rate = num(cost.get("referral_rate"))
    other = num(cost.get("other_per_unit"))
    storage_rate = num(cost.get("storage_rate"))
    if not unit_cost and not fba_fee:
        return {"amount": None, "rate": None, "target_rate": target_rate, "source": "missing", "note": "成本配置为空，无法核算利润。"}
    cogs = unit_cost * units
    logistics = first_leg * units
    referral = revenue * referral_rate
    fba = fba_fee * units
    other_cost = other * units
    storage = revenue * storage_rate
    amount = revenue - cogs - logistics - referral - fba - storage - other_cost - ad_spend - refunds
    return {
        "amount": amount,
        "rate": safe_div(amount, revenue),
        "target_rate": target_rate,
        "source": "computed",
        "breakdown": {
            "销售额": revenue,
            "采购成本": -cogs,
            "头程": -logistics,
            "佣金": -referral,
            "尾程配送费": -fba,
            "仓储费": -storage,
            "广告费": -ad_spend,
            "退款": -refunds,
            "其他": -other_cost,
        },
        "note": entry.get("rules_note") or "按配置成本与费用核算；广告费按实际花费扣减。",
    }


def _delta(cur: float, prev: float, kind: str) -> Dict[str, Any]:
    diff = cur - prev
    if kind in ("pp", "pct", "pct2"):
        digits = 2 if kind == "pct2" else 1
        sign = "+" if diff > 0 else ""
        return {"abs": diff, "rel": None, "label": f"{sign}{diff*100:.{digits}f}pp"}
    rel = safe_div(diff, abs(prev)) if prev else None
    return {"abs": diff, "rel": rel, "label": (f"{rel*100:+.1f}%" if rel is not None else "—")}


def _build_flags(ctx: Dict[str, Any], settings: Dict[str, Any]) -> List[Dict[str, str]]:
    t = settings.get("thresholds") or {}
    flags: List[Dict[str, str]] = []

    def add(level: str, area: str, text: str) -> None:
        flags.append({"level": level, "area": area, "text": text})

    attainment = ctx.get("attainment")
    target = ctx.get("target")
    revenue = ctx.get("revenue")
    if target and attainment is not None:
        gap = max(target - revenue, 0)
        if attainment < num(t.get("attainment_high"), 0.85):
            add("high", "销售", f"周目标只完成 {pct(attainment)}，缺口 {gap:,.0f} 美元，需在剩余周补量。")
        elif attainment < num(t.get("attainment_warn"), 0.95):
            add("warn", "销售", f"周目标完成 {pct(attainment)}，差 {gap:,.0f} 美元，节奏略慢。")
        else:
            add("good", "销售", f"周目标完成 {pct(attainment)}，按节奏达成。")

    margin = ctx.get("margin")
    target_margin = ctx.get("target_margin")
    if margin is not None and target_margin:
        gap = margin - target_margin
        if gap < -num(t.get("margin_gap_warn"), 0.02):
            add("high", "利润", f"实际利润率 {pct(margin)}，比目标 {pct(target_margin)} 低 {abs(gap)*100:.1f} 个百分点。")
        elif gap >= 0:
            add("good", "利润", f"实际利润率 {pct(margin)}，高于目标 {pct(target_margin)}（{pp(gap)}）。")

    acoas = ctx.get("acoas") or 0
    if acoas > num(t.get("acoas_warn"), 0.15):
        add("warn", "广告", f"ACoAS {pct(acoas)} 偏高（广告费/总销售额），检查高花费低转化活动。")

    rr = ctx.get("return_rate") or 0
    if rr > num(t.get("return_rate_warn"), 0.08):
        add("warn", "售后", f"退货率 {pct(rr)} 偏高，优先查尺寸/描述/质量差评。")

    wow = ctx.get("wow") or {}
    for key, area, label in (("sessions", "流量", "会话"), ("cvr", "转化", "整体 CVR")):
        item = wow.get(key) or {}
        if item.get("rel") is not None and item["rel"] < num(t.get(f"{key}_drop_warn"), -0.10):
            add("warn", area, f"{label}环比 {item['label']}，流量或承接在退。")

    share = ctx.get("ad_order_share") or 0
    if share > num(t.get("ad_order_share_warn"), 0.70):
        add("warn", "广告", f"广告订单占比 {pct(share)}，自然单偏弱。")

    comp = ctx.get("competitor") or {}
    if comp.get("price") and ctx.get("price"):
        gap = safe_div(comp["price"] - ctx["price"], ctx["price"])
        if gap < -num(t.get("competitor_price_gap_warn"), 0.05):
            add("warn", "竞品", f"竞品现价 {comp['price']:.2f}，比本品低 {abs(gap)*100:.1f}%，价格压力大。")
    if comp.get("rating") and ctx.get("rating"):
        diff = comp["rating"] - ctx["rating"]
        if diff > num(t.get("competitor_rating_gap_warn"), 0.2):
            add("info", "竞品", f"竞品评分 {comp['rating']:.1f}，高于本品 {diff:.1f} 分。")
    if comp.get("variation_delta"):
        direction = "增加" if comp["variation_delta"] > 0 else "减少"
        add("info", "竞品", f"竞品变体{direction} {abs(comp['variation_delta'])} 个（现 {comp.get('variation_count')} 个）。")
    if comp.get("deal"):
        add("info", "竞品", "竞品当前在做券/促销，注意价格带。")

    gaps = ctx.get("gaps") or []
    for gap in gaps:
        add("info", "数据", gap)
    return flags


def build(
    product: Dict[str, Any],
    week_start: dt.date,
    lingxing: Dict[str, Any],
    keywords_by_asin: Dict[str, Dict[str, Any]],
    competitor: Optional[Dict[str, Any]],
    targets: Dict[str, Any],
    settings: Dict[str, Any],
    *,
    demo: bool = False,
) -> Dict[str, Any]:
    settings = settings or {}
    entry = targets.get(product.get("spu")) or targets.get(product.get("id")) or {}
    this_raw = _block_metrics(lingxing.get("this") or {})
    last_raw = _block_metrics(lingxing.get("last") or {})
    this = derived(this_raw)
    last = derived(last_raw)

    target = weekly_target(entry, week_start)
    rounding = num(settings.get("target_rounding"), 100)
    if target and rounding >= 1:
        target = round(target / rounding) * rounding
    revenue = this["revenue"]
    profit = profit_block(entry, this_raw, revenue, this["units"], this["ad_spend"], this_raw.get("refunds", 0))
    margin = profit.get("rate")
    attainment = safe_div(revenue, target) if target else None

    wow = {}
    for label, key, kind in METRICS:
        cur, prev = this.get(key) or 0, last.get(key) or 0
        wow[key] = _delta(cur, prev, kind if kind in ("pct", "pct2") else "rel")
    for key in ("units", "revenue", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "sessions", "clicks", "orders", "impressions"):
        wow[key] = _delta(this[key], last[key], "rel")
    for key in ("ad_ctr", "ad_cvr"):
        wow[key] = _delta(this[key], last[key], "pct2")
    for key in ("acos", "cpa"):
        wow[key] = _delta(this[key], last[key], "rel")

    has_last = bool((lingxing.get("last") or {}).get("row_count"))

    # daily series + sparkline text
    daily = lingxing.get("this", {}).get("daily") or []
    daily_out = []
    for day in daily:
        row = derived({**{k: num(v) for k, v in day.items()}})
        daily_out.append({
            "date": day.get("date"),
            "units": row["units"],
            "revenue": row["revenue"],
            "sessions": row["sessions"],
            "clicks": row["clicks"],
            "impressions": row["impressions"],
            "orders": row["orders"],
            "ad_impressions": row["ad_impressions"],
            "ad_clicks": row["ad_clicks"],
            "ad_spend": row["ad_spend"],
            "ad_orders": row["ad_orders"],
            "ad_units": row["ad_units"],
            "ad_sales": row["ad_sales"],
            "ad_ctr": row["ad_ctr"],
            "ad_cvr": row["ad_cvr"],
            "cpc": row["cpc"],
            "acos": row["acos"],
            "acoas": row["acoas"],
        })

    campaigns = []
    for row in lingxing.get("campaigns") or []:
        spend = num(row.get("spend"))
        clicks = num(row.get("clicks"))
        orders = num(row.get("orders"))
        budget = num(row.get("budget"))
        campaigns.append({
            "name": row.get("name"),
            "parents": row.get("parents") or "",
            "portfolio": row.get("portfolio") or "",
            "state": row.get("state") or "",
            "match": row.get("match") or "",
            "budget": budget,
            "spend": spend,
            "budget_used": safe_div(spend, budget) if budget else None,
            "clicks": clicks,
            "orders": orders,
            "sales": num(row.get("sales")),
            "cvr": safe_div(orders, clicks),
            "cpa": safe_div(spend, orders),
            "acos": safe_div(spend, num(row.get("sales"))),
        })

    # 按广告组合汇总（用截断前的完整活动列表）
    live_campaigns = [c for c in campaigns if c["spend"] > 0]
    bucket: Dict[str, Dict[str, Any]] = {}
    for c in live_campaigns:
        key = c.get("portfolio") or "未分组"
        item = bucket.setdefault(key, {"campaigns": 0, "spend": 0.0, "sales": 0.0, "orders": 0.0, "clicks": 0.0})
        item["campaigns"] += 1
        item["spend"] += c["spend"]
        item["sales"] += c["sales"]
        item["orders"] += c["orders"]
        item["clicks"] += c["clicks"]
    total_pf_spend = sum(v["spend"] for v in bucket.values()) or 1.0
    portfolios: List[Dict[str, Any]] = []
    for key, v in bucket.items():
        portfolios.append({
            "portfolio": key,
            "campaigns": v["campaigns"],
            "spend": v["spend"],
            "sales": v["sales"],
            "orders": v["orders"],
            "clicks": v["clicks"],
            "acos": safe_div(v["spend"], v["sales"]),
            "cpa": safe_div(v["spend"], v["orders"]),
            "spend_share": safe_div(v["spend"], total_pf_spend),
        })
    portfolios.sort(key=lambda x: x["spend"], reverse=True)

    campaign_cap = int((settings.get("thresholds") or {}).get("campaign_rows", 12))
    campaigns = live_campaigns[:campaign_cap]
    total_spend = this["ad_spend"] or sum(c["spend"] for c in campaigns)
    for c in campaigns:
        c["spend_share"] = safe_div(c["spend"], total_spend)

    all_words = lingxing.get("keywords") or []
    total_kw_spend = sum(num(row.get("spend")) for row in all_words) or total_spend
    keywords_spend = []
    for row in all_words[: int((settings.get("thresholds") or {}).get("keyword_rows", 15))]:
        spend = num(row.get("spend"))
        clicks = num(row.get("clicks"))
        orders = num(row.get("orders"))
        keywords_spend.append({
            "keyword": row.get("keyword"),
            "parents": row.get("parents") or "",
            "clicks": clicks,
            "spend": spend,
            "orders": orders,
            "cvr": safe_div(orders, clicks),
            "cpa": safe_div(spend, orders),
            "spend_share": safe_div(spend, total_kw_spend),
        })

    by_parent_raw = lingxing.get("by_parent") or {}
    parent_ad_totals: Dict[str, float] = {}
    for p in product.get("parents") or []:
        pa = str(p.get("asin") or "")
        perf = by_parent_raw.get(pa) or {}
        if perf:
            parent_ad_totals[pa] = derived(_block_metrics(perf.get("this") or {})).get("ad_spend", 0)
    total_parent_ad_spend = sum(parent_ad_totals.values())

    parents = []
    for parent in product.get("parents") or []:
        asin = parent.get("asin")
        kw = keywords_by_asin.get(asin) or {}
        perf = by_parent_raw.get(asin) or {}
        m_this = derived(_block_metrics(perf.get("this") or {})) if perf else {}
        m_last = derived(_block_metrics(perf.get("last") or {})) if perf else {}
        ads_block = {
            "available": bool(perf),
            "ad_spend": m_this.get("ad_spend", 0),
            "ad_sales": m_this.get("ad_sales", 0),
            "ad_orders": m_this.get("ad_orders", 0),
            "ad_clicks": m_this.get("ad_clicks", 0),
            "ad_impressions": m_this.get("ad_impressions", 0),
            "ad_units": m_this.get("ad_units", 0),
            "ad_units_fallback": m_this.get("ad_units_fallback", True),
            "acos": m_this.get("acos"),
            "acoas": safe_div(m_this.get("ad_spend", 0), m_this.get("revenue", 0)),
            "cpc": m_this.get("cpc"),
            "ad_cvr": m_this.get("ad_cvr"),
            "revenue": m_this.get("revenue", 0),
            "units": m_this.get("units", 0),
            "spend_share": safe_div(m_this.get("ad_spend", 0), total_parent_ad_spend),
            "daily": [
                {
                    "date": day.get("date"),
                    **{
                        key: derived({k: num(v) for k, v in day.items()})[key]
                        for key in ("ad_impressions", "ad_clicks", "ad_ctr", "cpc", "ad_cvr", "ad_units", "ad_orders", "acos", "acoas")
                    },
                }
                for day in (perf.get("this") or {}).get("daily") or []
            ],
            "last_ad_spend": m_last.get("ad_spend", 0),
            "last_ad_sales": m_last.get("ad_sales", 0),
            "last_acos": m_last.get("acos"),
        }
        parents.append({
            "asin": asin,
            "label": parent.get("label") or "",
            "ads": ads_block,
            "keywords": {
                "source": kw.get("source"),
                "estimated_share": kw.get("estimated_share"),
                "captured_at": kw.get("captured_at"),
                "coverage": kw.get("coverage"),
                "total_terms": kw.get("total_terms"),
                "cover_count": kw.get("cover_count"),
                "terms": kw.get("terms") or [],
                "organic": kw.get("organic") or [],
                "ads": kw.get("ads") or [],
                "top80": kw.get("top80") or [],
                "notes": kw.get("notes") or [],
            },
        })

    gaps: List[str] = []
    if not daily:
        gaps.append("领星未返回日粒度数据，日销/广告日表按周合计展示。")
    if not target:
        gaps.append("缺周销售目标，达成率无法计算（config/targets.json）。")
    if profit.get("source") == "missing":
        gaps.append("缺成本配置，利润率无法核算。")
    for key, message in (lingxing.get("errors") or {}).items():
        if key.startswith("performance"):
            continue
        gaps.append(f"{key} 取数失败：{message}")
    if competitor and competitor.get("keywords", {}).get("error"):
        gaps.append(f"竞品关键词取数失败：{competitor['keywords']['error']}")

    comp_ctx = {
        "price": (competitor or {}).get("price"),
        "rating": (competitor or {}).get("rating"),
        "deal": (competitor or {}).get("deal"),
        "variation_delta": (competitor or {}).get("variation_delta"),
        "variation_count": (competitor or {}).get("variation_count"),
    }
    kw_flags: List[Dict[str, str]] = []
    first_terms = (parents[0]["keywords"].get("terms") if parents else []) or []
    top_terms = [t for t in first_terms if t.get("traffic_share")]
    if top_terms:
        lead = top_terms[0]
        if lead.get("organic_pos") and lead.get("organic_pos") <= 3:
            kw_flags.append({"level": "good", "area": "关键词", "text": f"核心词 “{lead['keyword']}” 自然位第 {lead['organic_pos']} 位，占抓取流量 {pct(lead.get('traffic_share'))}，入口稳定。"})
        elif lead.get("organic_pos"):
            kw_flags.append({"level": "info", "area": "关键词", "text": f"最大流量词 “{lead['keyword']}” 自然位第 {lead['organic_page']} 页 {lead['organic_pos']} 位，仍有上推空间。"})
    if parents:
        kw_meta = parents[0]["keywords"]
        total_terms = kw_meta.get("total_terms") or 0
        cover_count = kw_meta.get("cover_count") or 0
        if total_terms and cover_count and cover_count >= total_terms:
            kw_flags.append({"level": "info", "area": "关键词", "text": f"抓取到的 {total_terms} 个词全部落在前 80% 流量内，结构集中。"})

    own_price = num(product.get("price")) or 0
    ctx = {
        "attainment": attainment,
        "target": target,
        "revenue": revenue,
        "margin": margin,
        "target_margin": profit.get("target_rate"),
        "acoas": this["acoas"],
        "return_rate": this["return_rate"],
        "ad_order_share": this["ad_order_share"],
        "price": own_price,
        "rating": num(product.get("rating")) or 0,
        "wow": wow,
        "competitor": comp_ctx,
        "gaps": gaps,
    }
    flags = kw_flags + _build_flags(ctx, settings)

    findings = []
    for flag in sorted(flags, key=lambda f: {"high": 0, "warn": 1, "good": 2, "info": 3}.get(f["level"], 4)):
        findings.append(f"{flag['area']}｜{flag['text']}")
    if not findings:
        findings.append("本周无触发预警，按既定节奏执行即可。")

    data = {
        "meta": {
            "site": product.get("site", "US"),
            "site_label": {"US": "美国站", "DE": "德国站", "GB": "英国站", "CA": "加拿大站", "JP": "日本站"}.get(product.get("site", "US"), product.get("site", "")),
            "spu": product.get("spu"),
            "title": product.get("title") or product.get("spu"),
            "week_start": week_start.isoformat(),
            "week_end": (week_start + dt.timedelta(days=6)).isoformat(),
            "week_label": f"{week_start.month}月{week_start.day}日–{(week_start + dt.timedelta(days=6)).month}月{(week_start + dt.timedelta(days=6)).day}日",
            "iso_week": f"{week_start.isocalendar()[0]} 年第 {week_start.isocalendar()[1]} 周",
            "generated_at": dt.date.today().isoformat(),
            "currency": settings.get("currency", "USD"),
            "demo": demo,
            "keywords_source": next((p["keywords"].get("source") for p in parents if p["keywords"].get("source")), ""),
            "keywords_estimated": any(p["keywords"].get("estimated_share") for p in parents),
        },
        "overview": [{
            "spu": product.get("spu"),
            "units": this["units"],
            "revenue": revenue,
            "target": target,
            "monthly_target": num((entry.get("monthly") or {}).get(f"{week_start.year}-{week_start.month:02d}", entry.get("default_monthly"))),
            "attainment": attainment,
            "target_margin": profit.get("target_rate"),
            "actual_margin": margin,
            "profit": profit.get("amount"),
        }],
        "spus": [{
            "spu": product.get("spu"),
            "title": product.get("title"),
            "site": product.get("site"),
            "metrics": {**this, "wow": wow},
            "last": {**last},
            "has_last": has_last,
            "daily": daily_out,
            "target": target,
            "attainment": attainment,
            "profit": profit,
            "ads": {
                "summary": {
                    "impressions": this["ad_impressions"],
                    "clicks": this["ad_clicks"],
                    "ctr": this["ad_ctr"],
                    "cpc": this["cpc"],
                    "cvr": this["ad_cvr"],
                    "orders": this["ad_orders"],
                    "units": this["ad_units"],
                    "sales": this["ad_sales"],
                    "spend": this["ad_spend"],
                    "acos": this["acos"],
                    "cpa": this["cpa"],
                    "share": this["ad_order_share"],
                    "units_fallback": this.get("ad_units_fallback", False),
                },
                "daily": daily_out,
                "campaigns": campaigns,
                "portfolios": portfolios,
                "keywords": keywords_spend,
            },
            "parents": parents,
        }],
        "competitor": competitor,
        "flags": flags,
        "findings": findings,
        "gaps": gaps,
    }
    return data
