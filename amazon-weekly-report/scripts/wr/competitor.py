"""Competitor snapshot: basic info + price/promo/variation changes + keyword structure."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import collect_keywords
from .mcp import MCPError, rows_from
from .util import first, load_config, load_env, num, read_json, write_json


def _client(settings: Dict[str, Any]):
    from .collect_keywords import _sorftime_client  # local import keeps one config path
    return _sorftime_client(settings)


def _detail(row: Dict[str, Any]) -> Dict[str, Any]:
    coupon = num(first(row, ("coupon",)))
    savings = first(row, ("extra_savings",))
    has_promo = bool(savings) if isinstance(savings, list) else bool(savings)
    if coupon and coupon != -1:
        has_promo = True
    coupon_label = ""
    if coupon > 0:
        coupon_label = f"券 ${coupon:.2f}"
    elif coupon < -1:
        coupon_label = f"券 {abs(coupon):.0f}%"
    return {
        "title": str(first(row, ("title",)) or ""),
        "brand": str(first(row, ("brand",)) or ""),
        "price": num(first(row, ("price",))),
        "list_price": num(first(row, ("list_price",))),
        "coupon": coupon,
        "coupon_label": coupon_label,
        "deal": has_promo,
        "rating": num(first(row, ("star_rating", "rating"))),
        "reviews": num(first(row, ("review_count", "ratings"))),
        "variation_count": int(num(first(row, ("variation_count",)))),
        "parent_asin": str(first(row, ("parent_asin",)) or ""),
        "monthly_sales": num(first(row, ("monthly_sales_volume",))),
        "monthly_revenue": num(first(row, ("monthly_sales_amount",))),
        "launch_date": str(first(row, ("online_date", "listing_date")) or ""),
        "seller": str(first(row, ("seller_name",)) or ""),
    }


def collect(asin: str, site: str, out_dir: Path, url: str = "", force_keyword_source: str = "", week_end: str = "") -> Dict[str, Any]:
    load_env()
    settings = load_config("settings.json", {}) or {}
    notes: List[str] = []
    basic: Dict[str, Any] = {}
    variations: List[Dict[str, Any]] = []
    try:
        payload = _client(settings).call("product_detail", {"asin": asin, "amz_site": site})
        rows = rows_from(payload)
        row = rows[0] if rows else (payload.get("data") if isinstance(payload, dict) else {})
        if isinstance(row, dict):
            basic = _detail(row)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"product_detail: {exc}")

    try:
        payload = _client(settings).call("product_variations", {"asin": asin, "amz_site": site, "page": 1})
        for row in rows_from(payload):
            variations.append({
                "asin": str(first(row, ("asin",)) or ""),
                "property": str(first(row, ("property",)) or ""),
                "sales": num(first(row, ("sales_volume", "salesamount"))),
            })
    except Exception as exc:  # noqa: BLE001
        notes.append(f"product_variations: {exc}")

    history_path = out_dir / "history" / f"competitor-{asin}.json"
    previous = read_json(history_path, None)

    result: Dict[str, Any] = {
        "asin": asin,
        "site": site,
        "url": url or f"https://www.amazon.com/dp/{asin}",
        "snapshot_at": dt.date.today().isoformat(),
        **basic,
        "variations": variations,
        "notes": notes,
    }
    if previous:
        result["price_delta"] = (basic.get("price") or 0) - (previous.get("price") or 0)
        result["rating_delta"] = (basic.get("rating") or 0) - (previous.get("rating") or 0)
        result["reviews_delta"] = (basic.get("reviews") or 0) - (previous.get("reviews") or 0)
        result["variation_delta"] = (basic.get("variation_count") or 0) - (previous.get("variation_count") or 0)
        result["compared_to"] = previous.get("snapshot_at")
    else:
        result["price_delta"] = None
        result["rating_delta"] = None
        result["reviews_delta"] = None
        result["variation_delta"] = None
        result["compared_to"] = None

    try:
        kw = collect_keywords.collect(asin, site, out_dir, label="竞品", force=force_keyword_source, week_end=week_end)
        cover = [t for t in kw.get("top80") or []]
        result["keywords"] = {
            "source": kw.get("source"),
            "estimated_share": kw.get("estimated_share"),
            "coverage": kw.get("coverage"),
            "terms": kw.get("terms"),
            "organic80": [t for t in cover if t.get("organic_pos")],
            "ads80": [t for t in cover if t.get("ad_pos") or t.get("ad_label")],
            "top80": cover,
            "notes": kw.get("notes"),
        }
    except Exception as exc:  # noqa: BLE001
        result["keywords"] = {"terms": [], "organic80": [], "ads80": [], "top80": [], "error": str(exc)}

    write_json(out_dir / "raw" / f"competitor-{asin}.json", result)
    write_json(history_path, {"snapshot_at": result["snapshot_at"], **{k: basic.get(k) for k in ("price", "list_price", "rating", "reviews", "variation_count")}})
    return result
