"""Deterministic demo dataset for the weekly report.

Everything here is synthetic and labelled as 演示数据 in the report. It exists so
the full pipeline (raw -> data.json -> HTML) can be exercised without keys.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List

from . import collect_keywords
from .util import load_config, write_json

THIS = {
    "units": 1842, "revenue": 92100.0, "orders": 1774, "sessions": 61300, "clicks": 28400,
    "impressions": 3_780_000, "ad_impressions": 1_240_000, "ad_clicks": 18_900,
    "ad_spend": 11_420.0, "ad_orders": 1102, "ad_units": 1180, "ad_sales": 48_300.0, "returns": 86, "refunds": 2310.0,
}
LAST = {
    "units": 1694, "revenue": 84_600.0, "orders": 1628, "sessions": 58_900, "clicks": 27_900,
    "impressions": 3_620_000, "ad_impressions": 1_150_000, "ad_clicks": 18_100,
    "ad_spend": 10_980.0, "ad_orders": 1041, "ad_units": 1108, "ad_sales": 45_100.0, "returns": 79, "refunds": 2050.0,
}
WEIGHTS_THIS = [0.128, 0.132, 0.136, 0.141, 0.148, 0.155, 0.160]
WEIGHTS_LAST = [0.140, 0.136, 0.133, 0.138, 0.145, 0.152, 0.156]
REV_FACTOR = [0.97, 1.02, 0.99, 1.01, 1.00, 1.03, 0.98]


def _weights(base: List[float], factor: List[float] | None = None) -> List[float]:
    raw = [b * (f if factor else 1.0) for b, f in zip(base, factor or [1.0] * len(base))]
    total = sum(raw)
    return [r / total for r in raw]


def _split_int(total: int, weights: List[float]) -> List[int]:
    values = [int(round(total * w)) for w in weights]
    values[-1] += total - sum(values)
    return values


def _split_money(total: float, weights: List[float]) -> List[float]:
    values = [round(total * w, 2) for w in weights]
    values[-1] = round(values[-1] + total - sum(values), 2)
    return values


def _daily(monday: dt.date, totals: Dict[str, float], weights: List[float], rev_weights: List[float]) -> List[Dict[str, Any]]:
    ints = {k: _split_int(int(totals[k]), weights) for k in ("units", "orders", "sessions", "clicks", "impressions", "ad_impressions", "ad_clicks", "ad_orders", "ad_units", "returns")}
    money = {k: _split_money(totals[k], rev_weights if k in ("revenue", "ad_sales") else weights) for k in ("revenue", "ad_spend", "ad_sales", "refunds")}
    rows = []
    for i in range(7):
        row = {"date": (monday + dt.timedelta(days=i)).isoformat()}
        for key, values in ints.items():
            row[key] = values[i]
        for key, values in money.items():
            row[key] = values[i]
        row["profit"] = 0.0
        rows.append(row)
    return rows


CAMPAIGNS = [
    {"name": "SP-自动-核心词", "budget": 3000, "spend": 2980, "clicks": 5100, "orders": 318, "sales": 14200, "impressions": 320000},
    {"name": "SP-手动-精准-大词", "budget": 2500, "spend": 2760, "clicks": 4300, "orders": 205, "sales": 9000, "impressions": 260000},
    {"name": "SP-手动-长尾", "budget": 2000, "spend": 1640, "clicks": 3600, "orders": 240, "sales": 10400, "impressions": 180000},
    {"name": "SB-品牌词", "budget": 1500, "spend": 1120, "clicks": 1900, "orders": 128, "sales": 6400, "impressions": 210000},
    {"name": "SD-再营销", "budget": 1200, "spend": 1380, "clicks": 2100, "orders": 112, "sales": 4900, "impressions": 190000},
    {"name": "SP-竞品ASIN", "budget": 1000, "spend": 1540, "clicks": 1900, "orders": 99, "sales": 3400, "impressions": 80000},
]

KEYWORD_SPEND = [
    ("drafting chair", 3900, 2000, 273),
    ("tall office chair", 2650, 1760, 180),
    ("standing desk chair", 2200, 1520, 140),
    ("drafting chair with footrest", 1480, 1010, 108),
    ("high office chair", 1850, 1260, 97),
    ("tall desk chair", 1420, 940, 82),
    ("mesh drafting chair", 980, 640, 60),
    ("ergonomic drafting chair", 860, 590, 50),
    ("drafting stool", 740, 500, 40),
    ("counter height office chair", 720, 480, 34),
    ("office chair", 1650, 420, 31),
    ("drafting chair for artists", 450, 300, 7),
]

# (keyword, monthly search volume, organic page, organic pos, ad page, ad pos)
OWN_TERMS = [
    ("drafting chair", 99649, 1, 2, 1, 4),
    ("drafting chair with footrest", 5400, 1, 3, 1, 2),
    ("tall office chair", 14800, 1, 6, 1, 8),
    ("standing desk chair", 12100, 1, 5, 1, 12),
    ("tall office chair with footrest", 2200, 1, 4, 1, 6),
    ("mesh drafting chair", 3600, 1, 7, 2, 4),
    ("ergonomic drafting chair", 3900, 1, 8, 0, 0),
    ("drafting chair with lumbar support", 2100, 1, 9, 0, 0),
    ("standing desk chair with footrest", 1600, 1, 10, 1, 14),
    ("drafting chair for artists", 2900, 1, 11, 0, 0),
    ("adjustable drafting chair", 3300, 1, 12, 2, 5),
    ("drafting chair for home office", 1700, 1, 14, 0, 0),
    ("drafting table chair", 1200, 1, 18, 0, 0),
    ("tall desk chair", 8100, 2, 3, 1, 9),
    ("swivel drafting chair", 2600, 2, 2, 0, 0),
    ("drafting stool", 4400, 2, 1, 1, 15),
    ("high office chair", 22100, 2, 6, 1, 3),
    ("tall ergonomic chair", 5300, 2, 9, 2, 2),
    ("tall mesh office chair", 3100, 2, 10, 2, 8),
    ("drafting chair with wheels", 1900, 2, 7, 0, 0),
    ("counter height office chair", 8900, 2, 12, 1, 18),
    ("office chair", 993622, 3, 12, 1, 30),
    ("ergonomic office chair", 210010, 3, 8, 2, 14),
    ("computer chair", 218468, 3, 20, 2, 22),
    ("desk chair", 666704, 3, 30, 1, 40),
    ("bar stool", 98290, 2, 26, 1, 45),
]

COMP_TERMS = [
    ("drafting chair", 99649, 1, 2, 1, 4),
    ("office chair", 993622, 1, 34, 3, 29),
    ("desk chair", 666704, 1, 37, 2, 25),
    ("ergonomic office chair", 210010, 2, 19, 1, 7),
    ("office chairs", 166305, 2, 9, 1, 32),
    ("big and tall office chair", 113799, 2, 41, 1, 5),
    ("computer chair", 218468, 2, 25, 3, 7),
    ("home office desk chairs", 97296, 2, 28, 1, 36),
    ("counter height chairs", 66421, 1, 25, 2, 8),
    ("bar stool", 98290, 2, 26, 1, 76),
    ("ergonomic chair", 82741, 2, 27, 1, 19),
    ("adjustable desk", 115410, 2, 32, 1, 24),
]


# --------------------------------------------------------------------------- multi-SPU demo
SPU_PROFILES: List[Dict[str, Any]] = [
    {
        "spu": "66D50F", "site": "US", "title": "66D50F（美国站）", "price": 59.99, "rating": 4.2,
        "parents": ["B0XXXXXXXX"],
        "this": THIS, "last": LAST,
        "target": {"monthly": {"2026-11": 100000}, "default_monthly": 100000, "target_margin": 0.16,
                   "cost": {"unit_cost": 17.0, "first_leg": 3.8, "fba_fee": 7.0, "referral_rate": 0.15, "other_per_unit": 1.0},
                   "rules_note": "利润 = 销售额 − 采购成本 − 头程 − 佣金 − FBA 配送费 − 广告费 − 退款 − 其他。"},
        "keyword_shift": 0,
        "competitor": {"asin": "B0B41X9SMT", "price": 129.99, "list_price": 149.99, "rating": 4.3, "reviews": 3550,
                       "variation_count": 26, "variation_delta": 0, "price_delta": 0, "rating_delta": 0.0,
                       "reviews_delta": 37, "deal": False, "coupon_label": "", "brand": "Primy",
                       "title": "Primy Drafting Chair Tall Office Chair with Flip-up Armrests"},
    },
    {
        "spu": "71B22A", "site": "US", "title": "71B22A（美国站）", "price": 64.99, "rating": 4.5,
        "parents": ["B0H22BB001"],
        "this": {"units": 2310, "revenue": 128400.0, "orders": 2244, "sessions": 74200, "clicks": 35100,
                 "impressions": 4_600_000, "ad_impressions": 1_500_000, "ad_clicks": 21_600,
                 "ad_spend": 12_840.0, "ad_orders": 1180, "ad_units": 1262, "ad_sales": 61_200.0,
                 "returns": 71, "refunds": 2050.0},
        "last": {"units": 2180, "revenue": 121900.0, "orders": 2110, "sessions": 71300, "clicks": 33900,
                 "impressions": 4_420_000, "ad_impressions": 1_440_000, "ad_clicks": 20_800,
                 "ad_spend": 12_300.0, "ad_orders": 1128, "ad_units": 1206, "ad_sales": 58_400.0,
                 "returns": 66, "refunds": 1950.0},
        "target": {"monthly": {"2026-11": 480000}, "default_monthly": 480000, "target_margin": 0.18,
                   "cost": {"unit_cost": 18.8, "first_leg": 3.5, "fba_fee": 6.8, "referral_rate": 0.15, "other_per_unit": 1.0},
                   "rules_note": "利润 = 销售额 − 采购成本 − 头程 − 佣金 − FBA 配送费 − 广告费 − 退款 − 其他。"},
        "keyword_shift": -1,
        "competitor": {"asin": "B0COMP0001", "price": 109.99, "list_price": 129.99, "rating": 4.5, "reviews": 2100,
                       "variation_count": 14, "variation_delta": 2, "price_delta": -5, "rating_delta": 0.1,
                       "reviews_delta": 52, "deal": True, "coupon_label": "券 $5.00", "brand": "DemoBrand",
                       "title": "Demo 竞品 A · 高背办公椅"},
    },
    {
        "spu": "88C31D", "site": "US", "title": "88C31D（美国站）", "price": 49.99, "rating": 4.0,
        "parents": ["B0C11AA001", "B0C11AA002"],
        "this": {"units": 620, "revenue": 42000.0, "orders": 590, "sessions": 31500, "clicks": 14200,
                 "impressions": 1_900_000, "ad_impressions": 720_000, "ad_clicks": 9_800,
                 "ad_spend": 8_820.0, "ad_orders": 320, "ad_units": 338, "ad_sales": 19_600.0,
                 "returns": 61, "refunds": 2940.0},
        "last": {"units": 700, "revenue": 47500.0, "orders": 668, "sessions": 33000, "clicks": 15100,
                 "impressions": 2_000_000, "ad_impressions": 760_000, "ad_clicks": 10_300,
                 "ad_spend": 8_100.0, "ad_orders": 352, "ad_units": 370, "ad_sales": 21_800.0,
                 "returns": 48, "refunds": 2500.0},
        "target": {"monthly": {"2026-11": 300000}, "default_monthly": 300000, "target_margin": 0.15,
                   "cost": {"unit_cost": 22.0, "first_leg": 4.0, "fba_fee": 7.0, "referral_rate": 0.15, "other_per_unit": 1.0},
                   "rules_note": "利润 = 销售额 − 采购成本 − 头程 − 佣金 − FBA 配送费 − 广告费 − 退款 − 其他。"},
        "keyword_shift": 4,
        "competitor": {"asin": "B0COMP0002", "price": 45.99, "list_price": 59.99, "rating": 4.1, "reviews": 860,
                       "variation_count": 8, "variation_delta": -3, "price_delta": -3, "rating_delta": -0.1,
                       "reviews_delta": 24, "deal": True, "coupon_label": "券 10%", "brand": "DemoBrand",
                       "title": "Demo 竞品 B · 入门办公椅"},
    },
]


def _terms(rows: list, shift: int = 0) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        opage, opos, apage, apos = row[2], row[3], row[4], row[5]
        if shift:
            if opos:
                opos = opos + shift if shift > 0 else max(1, opos + shift)
                if opos > 48:
                    opage, opos = (opage + 1 if opage < 3 else 3), 1
            if apos:
                apos = apos + shift if shift > 0 else max(1, apos + shift)
                if apos > 60:
                    apage, apos = (apage + 1 if apage < 3 else 3), 1
        out.append({
            "keyword": row[0], "search_volume": row[1], "traffic_share": 0.0,
            "organic_page": opage, "organic_pos": opos, "ad_page": apage, "ad_pos": apos,
        })
    return out


def _keyword_payload(rows: list, shift: int = 0, source: str = "sorftime") -> Dict[str, Any]:
    settings = load_config("settings.json", {}) or {}
    terms = _terms(rows, shift)
    collect_keywords.estimate_shares(terms)
    data = {"source": source, "estimated_share": True, "terms": terms, "notes": []}
    return collect_keywords.shape(data, settings)


def _scaled_campaigns(totals: Dict[str, float]) -> List[Dict[str, Any]]:
    spend_ratio = totals["ad_spend"] / 11420.0
    click_ratio = totals["ad_clicks"] / 18900.0
    order_ratio = totals["ad_orders"] / 1102.0
    sales_ratio = totals["ad_sales"] / 48300.0
    rows = []
    for camp in CAMPAIGNS:
        rows.append({
            "name": camp["name"],
            "budget": round(camp["budget"] * spend_ratio),
            "spend": round(camp["spend"] * spend_ratio, 2),
            "clicks": round(camp["clicks"] * click_ratio),
            "orders": round(camp["orders"] * order_ratio),
            "sales": round(camp["sales"] * sales_ratio, 2),
            "impressions": round(camp["impressions"] * click_ratio),
        })
    return rows


def _scaled_keywords(totals: Dict[str, float]) -> List[Dict[str, Any]]:
    spend_ratio = totals["ad_spend"] / 11420.0
    click_ratio = totals["ad_clicks"] / 18900.0
    order_ratio = totals["ad_orders"] / 1102.0
    return [
        {"keyword": word, "clicks": round(clicks * click_ratio), "spend": round(spend * spend_ratio, 2),
         "orders": round(orders * order_ratio), "sales": round(orders * order_ratio * 44.0, 2)}
        for word, clicks, spend, orders in KEYWORD_SPEND
    ]


def write_multi(root: Path, monday: dt.date) -> Dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    products, targets = [], {}
    last_monday = monday - dt.timedelta(days=7)
    for profile in SPU_PROFILES:
        data_dir = root / f"{profile['site']}-{profile['spu']}"
        (data_dir / "raw").mkdir(parents=True, exist_ok=True)
        this_daily = _daily(monday, profile["this"], _weights(WEIGHTS_THIS), _weights(WEIGHTS_THIS, REV_FACTOR))
        last_daily = _daily(last_monday, profile["last"], _weights(WEIGHTS_LAST), _weights(WEIGHTS_LAST, REV_FACTOR))
        keys = ("units", "revenue", "orders", "sessions", "clicks", "impressions", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")

        def block(daily, start):
            return {"aggregate": {k: round(sum(d[k] for d in daily), 2) for k in keys}, "daily": daily,
                    "row_count": 7, "columns": list(keys), "range": [start.isoformat(), (start + dt.timedelta(days=6)).isoformat()]}

        lingxing = {
            "source": "lingxing", "week_start": monday.isoformat(),
            "this": block(this_daily, monday), "last": block(last_daily, last_monday),
            "campaigns": _scaled_campaigns(profile["this"]),
            "keywords": _scaled_keywords(profile["this"]),
            "profit": 0.0, "errors": {},
        }
        write_json(data_dir / "raw" / "lingxing.json", lingxing)

        kw = _keyword_payload(OWN_TERMS, profile["keyword_shift"])
        for asin in profile["parents"]:
            payload = dict(kw)
            payload.update({"asin": asin, "site": profile["site"], "captured_at": (monday + dt.timedelta(days=1)).isoformat(), "label": ""})
            write_json(data_dir / "raw" / f"keywords-{asin}.json", payload)

        comp = dict(profile["competitor"])
        comp_kw = _keyword_payload(COMP_TERMS, 0)
        comp_cover = comp_kw.get("top80") or []
        comp["keywords"] = {
            "source": comp_kw.get("source"), "estimated_share": True,
            "terms": comp_kw.get("terms"), "top80": comp_cover,
            "organic80": [t for t in comp_cover if t.get("organic_pos")],
            "ads80": [t for t in comp_cover if t.get("ad_pos")],
            "notes": [],
        }
        comp["monthly_sales"] = 2977
        comp["snapshot_at"] = (monday + dt.timedelta(days=2)).isoformat()
        comp["compared_to"] = (monday - dt.timedelta(days=4)).isoformat()
        write_json(data_dir / "raw" / f"competitor-{comp['asin']}.json", comp)
        write_json(data_dir / "history" / f"competitor-{comp['asin']}.json", {
            "snapshot_at": comp["compared_to"], "price": comp["price"] - comp["price_delta"],
            "list_price": comp["list_price"], "rating": comp["rating"] - comp["rating_delta"],
            "reviews": comp["reviews"] - comp["reviews_delta"], "variation_count": comp["variation_count"] - comp["variation_delta"],
        })

        products.append({
            "id": profile["spu"], "spu": profile["spu"], "site": profile["site"], "title": profile["title"],
            "parents": [{"asin": a, "label": ""} for a in profile["parents"]],
            "competitor": {"asin": comp["asin"], "url": f"https://www.amazon.com/dp/{comp['asin']}"},
            "price": profile["price"], "rating": profile["rating"], "enabled": True,
        })
        targets[profile["spu"]] = profile["target"]
    return {"products": products, "targets": targets}


# --------------------------------------------------------------------------- legacy single demo
def _terms_single(rows: list) -> List[Dict[str, Any]]:
    return _terms(rows, 0)


def _keyword_payload_single(rows: list, source: str = "sorftime") -> Dict[str, Any]:
    settings = load_config("settings.json", {}) or {}
    terms = _terms_single(rows)
    collect_keywords.estimate_shares(terms)
    data = {"source": source, "estimated_share": True, "terms": terms, "notes": []}
    return collect_keywords.shape(data, settings)


def write_demo(data_dir: Path, week_start: dt.date, product: Dict[str, Any], competitor_asin: str) -> Dict[str, Any]:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)

    this_daily = _daily(week_start, THIS, _weights(WEIGHTS_THIS), _weights(WEIGHTS_THIS, REV_FACTOR))
    last_monday = week_start - dt.timedelta(days=7)
    last_daily = _daily(last_monday, LAST, _weights(WEIGHTS_LAST), _weights(WEIGHTS_LAST, REV_FACTOR))

    def block(daily: List[Dict[str, Any]], monday: dt.date) -> Dict[str, Any]:
        keys = ("units", "revenue", "orders", "sessions", "clicks", "impressions", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")
        aggregate = {k: round(sum(d[k] for d in daily), 2) for k in keys}
        return {"aggregate": aggregate, "daily": daily, "row_count": 7, "columns": list(keys), "range": [monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()]}

    lingxing = {
        "source": "lingxing",
        "week_start": week_start.isoformat(),
        "this": block(this_daily, week_start),
        "last": block(last_daily, last_monday),
        "campaigns": CAMPAIGNS,
        "keywords": [
            {"keyword": word, "clicks": clicks, "spend": spend, "orders": orders, "sales": round(orders * 44.0, 2)}
            for word, clicks, spend, orders in KEYWORD_SPEND
        ],
        "profit": 0.0,
        "errors": {},
    }
    write_json(data_dir / "raw" / "lingxing.json", lingxing)

    for parent in product.get("parents") or []:
        asin = parent.get("asin")
        kw = _keyword_payload_single(OWN_TERMS)
        kw.update({"asin": asin, "site": product.get("site", "US"), "captured_at": (week_start + dt.timedelta(days=1)).isoformat(), "label": parent.get("label", "")})
        write_json(data_dir / "raw" / f"keywords-{asin}.json", kw)

    comp_kw = _keyword_payload_single(COMP_TERMS)
    cover = comp_kw.get("top80") or []
    competitor = {
        "asin": competitor_asin,
        "site": product.get("site", "US"),
        "url": f"https://www.amazon.com/dp/{competitor_asin}",
        "snapshot_at": (week_start + dt.timedelta(days=2)).isoformat(),
        "title": "Primy Drafting Chair Tall Office Chair with Flip-up Armrests, Ergonomic Computer Standing Desk Chair with Lumbar Support and Adjustable Footrest Ring (Black)",
        "brand": "Primy",
        "price": 129.99,
        "list_price": 149.99,
        "coupon": 0.0,
        "coupon_label": "",
        "deal": False,
        "rating": 4.3,
        "reviews": 3550,
        "variation_count": 26,
        "parent_asin": "B0CLS1P7Q9",
        "monthly_sales": 2977,
        "monthly_revenue": 386980.23,
        "launch_date": "2022-08-04",
        "seller": "Primy-Super",
        "variations": [],
        "notes": [],
        "price_delta": 0.0,
        "rating_delta": 0.0,
        "reviews_delta": 37,
        "variation_delta": 0,
        "compared_to": "2026-11-11",
        "keywords": {
            "source": "sorftime",
            "estimated_share": True,
            "coverage": comp_kw.get("coverage"),
            "terms": comp_kw.get("terms"),
            "organic80": [t for t in cover if t.get("organic_pos")],
            "ads80": [t for t in cover if t.get("ad_pos")],
            "top80": cover,
            "notes": [],
        },
    }
    write_json(data_dir / "raw" / f"competitor-{competitor_asin}.json", competitor)
    write_json(data_dir / "history" / f"competitor-{competitor_asin}.json", {
        "snapshot_at": "2026-11-11", "price": 129.99, "list_price": 149.99,
        "rating": 4.3, "reviews": 3513, "variation_count": 26,
    })
    return {"lingxing": lingxing, "competitor": competitor}
