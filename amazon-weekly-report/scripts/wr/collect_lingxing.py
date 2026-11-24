"""Lingxing (领星 ERP) collector.

Design notes
------------
Lingxing exposes ~300 read-only MCP tools. The four this report needs are fixed
by the official tool catalogue, but parameter names and response field names can
vary between tenants/versions. So:

1. tool names live in ``config/lingxing.json`` and can be edited without code;
2. arguments are auto-filled from the live JSON schema (``lingxing-schema``);
3. response fields are resolved through ``field_aliases`` and anything unmapped
   is reported instead of guessed.

Nothing here fabricates a value: a missing field stays missing and becomes a gap.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .mcp import MCPClient, MCPError, rows_from
from .util import env, first, load_config, load_env, num, read_json, write_json

CANONICAL = ("performance", "campaign", "keyword", "profit", "shops", "listing")


# --------------------------------------------------------------------------- config
def _cfg() -> Dict[str, Any]:
    return load_config("lingxing.json", {}) or {}


def client() -> MCPClient:
    load_env()
    cfg = _cfg()
    url = env("LINGXING_MCP_URL", cfg.get("url", ""))
    key = env("LINGXING_MCP_KEY", "")
    return MCPClient(
        url,
        key,
        auth=cfg.get("auth", "header"),
        key_param=cfg.get("key_param", "X-Mcp-Key"),
        label="领星",
    )


def tool_name(canonical: str) -> str:
    return (_cfg().get("tools") or {}).get(canonical, "") or ""


# --------------------------------------------------------------------------- schema
def dump_schemas(path: Optional[Path] = None) -> Dict[str, Any]:
    cfg = _cfg()
    c = client()
    tools = c.list_tools()
    out = {
        "provider": "lingxing",
        "url": c.url.split("?")[0],
        "tool_count": len(tools),
        "mapped": {k: v for k, v in (cfg.get("tools") or {}).items()},
        "tools": {t.get("name"): t for t in tools if t.get("name")},
    }
    if path:
        write_json(path, out)
    return out


def doctor() -> Dict[str, Any]:
    cfg = _cfg()
    load_env()
    if not env("LINGXING_MCP_KEY"):
        return {"ok": False, "error": "未配置 LINGXING_MCP_KEY：请到工作台「数据源」里配置领星并保存（会自动注入），或在本技能 .env 里填 LINGXING_MCP_KEY"}
    c = client()
    try:
        tools = c.list_tools()
    except MCPError as exc:
        return {"ok": False, "error": str(exc), "url": c.url.split("?")[0]}
    names = {t.get("name") for t in tools}
    mapped = cfg.get("tools") or {}
    if "action" in names and "search" in names:
        return {"ok": True, "mode": "gateway", "tool_count": len(tools), "mapped": mapped,
                "missing": [], "unmapped": [], "tools": sorted(n for n in names if n)}
    missing = [f"{k} -> {v}" for k, v in mapped.items() if v and v not in names]
    unmapped = [k for k in CANONICAL if not mapped.get(k)]
    return {
        "ok": not missing and not unmapped,
        "tool_count": len(tools),
        "mapped": mapped,
        "missing": missing,
        "unmapped": unmapped,
        "tools": sorted(n for n in names if n),
    }


# --------------------------------------------------------------------------- args
_CTX_ALIASES = {
    "start": ("start_date", "startdate", "date_start", "begin_date", "start", "startTime", "from"),
    "end": ("end_date", "enddate", "date_end", "finish_date", "end", "endTime", "to"),
    "site": ("country", "country_code", "marketplace", "site", "region"),
    "spu": ("spu", "spu_list", "spu_code", "product_spu"),
    "asin": ("asin", "asin_list", "child_asin", "parent_asin"),
    "sid": ("sid", "sids", "shop_id", "shop_ids", "sid_list"),
    "page": ("page", "page_index", "page_no", "current"),
    "size": ("page_size", "length", "size", "limit", "rows"),
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_prop(prop: str, aliases: Iterable[str]) -> bool:
    p = _norm(prop)
    for alias in aliases:
        a = _norm(alias)
        if p == a or p.endswith(a) or a.endswith(p):
            return True
    return False


def autofill_args(schema: Dict[str, Any], ctx: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fill known scalar params from context; leave everything else out."""
    props = (schema or {}).get("properties") or {}
    args: Dict[str, Any] = {}
    for prop in props:
        for key in ("start", "end", "site", "spu", "asin", "sid"):
            if ctx.get(key) and _match_prop(prop, _CTX_ALIASES[key]):
                args[prop] = ctx[key]
                break
        else:
            if _match_prop(prop, _CTX_ALIASES["page"]):
                args[prop] = 1
            elif _match_prop(prop, _CTX_ALIASES["size"]):
                args[prop] = 200
    for key, value in (overrides or {}).items():
        args[key] = value
    return _substitute(args, ctx)


def _substitute(value: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: str(ctx.get(m.group(1), "")), value)
    if isinstance(value, list):
        return [_substitute(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, ctx) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- normalize
def _alias(cfg: Dict[str, Any], key: str) -> List[str]:
    return ((cfg.get("field_aliases") or {}).get(key) or [key])


def _pick(row: Dict[str, Any], cfg: Dict[str, Any], key: str) -> Any:
    return first(row, _alias(cfg, key))


def _date_of(row: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    value = _pick(row, cfg, "date")
    return str(value or "")[:10].replace("/", "-")


def normalize_week(payload: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one performance payload into {aggregate, daily, rows}."""
    rows = rows_from(payload)
    aggregate: Dict[str, float] = {}
    daily: Dict[str, Dict[str, float]] = {}
    keys = ("units", "revenue", "sessions", "clicks", "impressions", "orders", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")
    for row in rows:
        metrics = {key: num(_pick(row, cfg, key)) for key in keys}
        date = _date_of(row, cfg)
        if date:
            bucket = daily.setdefault(date, {key: 0.0 for key in keys})
            for key, value in metrics.items():
                bucket[key] += value
        for key, value in metrics.items():
            aggregate[key] = aggregate.get(key, 0.0) + value
    if not rows:
        aggregate = {key: 0.0 for key in keys}
    return {
        "aggregate": aggregate,
        "daily": [{"date": d, **v} for d, v in sorted(daily.items())],
        "row_count": len(rows),
        "columns": sorted({k for row in rows for k in row})[:100],
    }


def normalize_campaigns(payload: Any, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    campaigns = []
    for row in rows_from(payload):
        campaigns.append({
            "name": str(_pick(row, cfg, "campaign_name") or "未命名活动"),
            "budget": num(_pick(row, cfg, "campaign_budget")),
            "spend": num(_pick(row, cfg, "ad_spend")),
            "clicks": num(_pick(row, cfg, "ad_clicks") or _pick(row, cfg, "clicks")),
            "impressions": num(_pick(row, cfg, "ad_impressions")),
            "orders": num(_pick(row, cfg, "ad_orders") or _pick(row, cfg, "orders")),
            "sales": num(_pick(row, cfg, "ad_sales") or _pick(row, cfg, "revenue")),
        })
    return sorted(campaigns, key=lambda c: c["spend"], reverse=True)


def normalize_keywords(payload: Any, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    keywords: Dict[str, Dict[str, Any]] = {}
    for row in rows_from(payload):
        word = str(_pick(row, cfg, "keyword") or "").strip().lower()
        if not word:
            continue
        item = keywords.setdefault(word, {"keyword": word, "clicks": 0.0, "spend": 0.0, "orders": 0.0, "sales": 0.0})
        item["clicks"] += num(_pick(row, cfg, "ad_clicks") or _pick(row, cfg, "clicks"))
        item["spend"] += num(_pick(row, cfg, "ad_spend"))
        item["orders"] += num(_pick(row, cfg, "ad_orders") or _pick(row, cfg, "orders"))
        item["sales"] += num(_pick(row, cfg, "ad_sales") or _pick(row, cfg, "revenue"))
    return sorted(keywords.values(), key=lambda x: x["spend"], reverse=True)


def normalize_profit(payload: Any, cfg: Dict[str, Any]) -> float:
    total = 0.0
    for row in rows_from(payload):
        total += num(_pick(row, cfg, "profit"))
    if not total and isinstance(payload, dict):
        total = num(_pick(payload, cfg, "profit"))
    return total


# --------------------------------------------------------------------------- collect
def _collect_direct(product: Dict[str, Any], week_start: dt.date, out_dir: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fetch this week + last week raw payloads and return a normalized dict."""
    cfg = _cfg()
    raw_dir = out_dir / "raw" / "lingxing"
    raw_dir.mkdir(parents=True, exist_ok=True)
    schemas_path = Path(__file__).resolve().parents[2] / "config" / "lingxing.schema.json"
    schemas = (read_json(schemas_path, {}) or {}).get("tools", {}) if schemas_path.exists() else {}
    mcp = client()
    if not schemas:
        schemas = {t.get("name"): t for t in mcp.list_tools()}

    sid = ""
    shops = product.get("shops") or []
    if shops:
        sid = str(shops[0].get("sid") or "")

    this_start = week_start
    this_end = week_start + dt.timedelta(days=6)
    last_start = week_start - dt.timedelta(days=7)
    last_end = week_start - dt.timedelta(days=1)

    base_ctx = {
        "site": product.get("site", "US"),
        "spu": product.get("spu", ""),
        "asin": (product.get("parents") or [{}])[0].get("asin", ""),
        "sid": sid,
    }

    def call(canonical: str, start: dt.date, end: dt.date, extra_ctx: Optional[Dict[str, Any]] = None) -> Any:
        name = tool_name(canonical)
        if not name:
            raise MCPError(f"领星未配置 {canonical} 工具名（config/lingxing.json）")
        schema = schemas.get(name) or {}
        ctx = {**base_ctx, "start": start.isoformat(), "end": end.isoformat(), **(extra_ctx or {})}
        overrides = (cfg.get("args") or {}).get(canonical) or {}
        args = autofill_args(schema, ctx, overrides)
        payload = mcp.call(name, args)
        write_json(raw_dir / f"{canonical}-{start.isoformat()}.json", payload)
        write_json(raw_dir / f"{canonical}-{start.isoformat()}.args.json", args)
        return payload

    errors: Dict[str, str] = {}
    result: Dict[str, Any] = {
        "source": "lingxing",
        "week_start": this_start.isoformat(),
        "this": {"aggregate": {}, "daily": [], "row_count": 0},
        "last": {"aggregate": {}, "daily": [], "row_count": 0},
        "campaigns": [],
        "keywords": [],
        "profit": 0.0,
        "errors": errors,
    }

    wanted = set(only or ["performance", "campaign", "keyword", "profit"])
    if "performance" in wanted:
        for tag, start, end in (("this", this_start, this_end), ("last", last_start, last_end)):
            try:
                payload = call("performance", start, end)
                result[tag] = normalize_week(payload, cfg)
                result[tag]["range"] = [start.isoformat(), end.isoformat()]
            except Exception as exc:  # noqa: BLE001
                errors[f"performance-{tag}"] = str(exc)
    if "campaign" in wanted:
        try:
            result["campaigns"] = normalize_campaigns(call("campaign", this_start, this_end), cfg)
        except Exception as exc:  # noqa: BLE001
            errors["campaign"] = str(exc)
    if "keyword" in wanted:
        try:
            result["keywords"] = normalize_keywords(call("keyword", this_start, this_end), cfg)
        except Exception as exc:  # noqa: BLE001
            errors["keyword"] = str(exc)
    if "profit" in wanted:
        try:
            payload = call("profit", this_start, this_end, {"asin": ""})
            result["profit"] = normalize_profit(payload, cfg)
        except Exception as exc:  # noqa: BLE001
            errors["profit"] = str(exc)

    write_json(out_dir / "raw" / "lingxing.json", result)
    return result


_GATEWAY: Dict[str, bool] = {}

PERF_KEYS = ("units", "revenue", "orders", "sessions", "clicks", "impressions", "ad_impressions", "ad_clicks", "ad_spend", "ad_orders", "ad_units", "ad_sales", "returns", "refunds", "profit")


def is_gateway() -> bool:
    if "value" not in _GATEWAY:
        names = {t.get("name") for t in client().list_tools()}
        _GATEWAY["value"] = "action" in names and "search" in names
    return _GATEWAY["value"]


def action(tool_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    out = client().call("action", {"toolId": tool_id, "params": params})
    if not out.get("success", True):
        raise MCPError(f"领星 {tool_id} 失败：{out.get('msg') or out}")
    return out.get("data") or {}


def _rows(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    value = payload.get("data")
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        for key in ("list", "data", "records"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
    return []


def shops_for(site: str) -> List[Dict[str, Any]]:
    data = action("ad_auth_shops", {})
    rows = data.get("data") or []
    return [r for r in rows if str(r.get("country", "")).upper() == site.upper()]


def _performance(asin: str, start: str, end: str, sids: str) -> List[Dict[str, Any]]:
    params = {
        "start_date": start,
        "end_date": end,
        "date_type": "purchase",
        "date_view_type": "day",
        "date_view_order_type": 0,
        "summary_field": "parent_asin",
        "summary_field_level1": "parent_asin",
        "search_value": [asin],
        "sids": sids,
        "currency_code": "USD",
        "length": 50,
        "offset": 0,
        "sort_field": "volume",
        "sort_type": "desc",
    }
    return _rows(action("query_product_performance_asin_lists", params))


def _map_perf(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": str(row.get("rdate") or "")[:10],
        "units": num(row.get("volume")),
        "revenue": num(row.get("amount")),
        "orders": num(row.get("order_items")),
        "sessions": num(row.get("sessions_total")),
        "clicks": num(row.get("clicks")),
        "impressions": num(row.get("impressions")),
        "ad_impressions": num(row.get("impressions")),
        "ad_clicks": num(row.get("clicks")),
        "ad_spend": num(row.get("spend")),
        "ad_orders": num(row.get("ad_order_quantity")),
        "ad_units": num(row.get("ads_sales_volume_quantity")),
        "ad_sales": num(row.get("ad_sales_amount")),
        "returns": num(row.get("return_goods_count")),
        "refunds": num(row.get("return_amount")),
        "profit": num(row.get("gross_profit")),
    }


def _merge_daily(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bucket: Dict[str, Dict[str, float]] = {}
    for row in rows:
        date = row.get("date")
        if not date:
            continue
        item = bucket.setdefault(date, {k: 0.0 for k in PERF_KEYS})
        for key in PERF_KEYS:
            item[key] += num(row.get(key))
    return [{"date": d, **v} for d, v in sorted(bucket.items())]


def _block(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    daily = _merge_daily(rows)
    aggregate = {key: round(sum(num(d.get(key)) for d in daily), 2) for key in PERF_KEYS}
    return {"aggregate": aggregate, "daily": daily, "row_count": len(daily), "columns": list(PERF_KEYS)}


def _campaigns(name: str, start: str, end: str, profiles: List[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    page = 1
    while page <= 10:
        rows = _rows(action("ad_campaign_report", {
            "report_date": f"{start} - {end}",
            "profile_ids": profiles,
            "name": name,
            "page": page,
            "length": 100,
            "sort_field": "spends",
            "sort_type": "desc",
        }))
        if not rows:
            break
        for row in rows:
            cid = str(row.get("campaign_id") or "")
            cname = str(row.get("name") or "")
            if not cname or not cid or cid in seen:
                continue
            seen.add(cid)
            budget = num(row.get("budget"))
            if budget and str(row.get("budget_type") or "") != "lifetime":
                budget *= 7
            result.append({
                "campaign_id": cid,
                "name": cname,
                "budget": budget,
                "spend": num(row.get("spends")),
                "clicks": num(row.get("clicks")),
                "orders": num(row.get("orders")),
                "sales": num(row.get("sales")),
                "impressions": num(row.get("impressions")),
            })
        if len(rows) < 100:
            break
        page += 1
    return sorted(result, key=lambda c: c["spend"], reverse=True)


def _keywords(campaign_ids: List[str], start: str, end: str, profiles: List[str]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for index in range(0, len(campaign_ids), 50):
        chunk = campaign_ids[index:index + 50]
        for page in (1, 2):
            rows = _rows(action("ad_campaign_keyword_report", {
                "report_date": f"{start} - {end}",
                "profile_ids": profiles,
                "campaign_id": chunk,
                "page": page,
                "length": 200,
                "sort_field": "spends",
                "sort_type": "desc",
            }))
            if not rows:
                break
            for row in rows:
                word = str(row.get("keyword_text") or "").strip().lower()
                if not word:
                    continue
                item = merged.setdefault(word, {"keyword": word, "clicks": 0.0, "spend": 0.0, "orders": 0.0, "sales": 0.0})
                item["clicks"] += num(row.get("clicks"))
                item["spend"] += num(row.get("spends"))
                item["orders"] += num(row.get("orders"))
                item["sales"] += num(row.get("sales"))
            if len(rows) < 200:
                break
    return sorted(merged.values(), key=lambda x: x["spend"], reverse=True)


def _collect_gateway(product: Dict[str, Any], week_start: dt.date, out_dir: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    site = product.get("site", "US")
    spu = str(product.get("spu", ""))
    shops = shops_for(site)
    if not shops:
        raise MCPError(f"领星没有 {site} 的广告授权店铺")
    sids = ",".join(str(s.get("sid")) for s in shops if s.get("sid"))
    profiles = [str(s.get("profile_id")) for s in shops if s.get("profile_id")]

    this_start = week_start.isoformat()
    this_end = (week_start + dt.timedelta(days=6)).isoformat()
    last_start = (week_start - dt.timedelta(days=7)).isoformat()
    last_end = (week_start - dt.timedelta(days=1)).isoformat()

    errors: Dict[str, str] = {}
    this_rows: List[Dict[str, Any]] = []
    last_rows: List[Dict[str, Any]] = []
    raw_rows: Dict[str, Any] = {}
    wanted = set(only or ["performance", "campaign", "keyword"])

    if "performance" in wanted:
        for parent in product.get("parents") or []:
            asin = str(parent.get("asin") or "")
            if not asin:
                continue
            try:
                rows = _performance(asin, this_start, this_end, sids)
                raw_rows[f"{asin}-this"] = rows
                this_rows.extend(_map_perf(r) for r in rows)
            except Exception as exc:  # noqa: BLE001
                errors[f"performance-{asin}-this"] = str(exc)
            try:
                rows = _performance(asin, last_start, last_end, sids)
                raw_rows[f"{asin}-last"] = rows
                last_rows.extend(_map_perf(r) for r in rows)
            except Exception as exc:  # noqa: BLE001
                errors[f"performance-{asin}-last"] = str(exc)

    campaigns: List[Dict[str, Any]] = []
    keywords: List[Dict[str, Any]] = []
    if "campaign" in wanted:
        try:
            suffix = re.sub(r"^[A-Z]{2,5}-", "", spu)
            campaigns = _campaigns(suffix or spu, this_start, this_end, profiles)
        except Exception as exc:  # noqa: BLE001
            errors["campaign"] = str(exc)
    if "keyword" in wanted and campaigns:
        try:
            keywords = _keywords([c["campaign_id"] for c in campaigns], this_start, this_end, profiles)
        except Exception as exc:  # noqa: BLE001
            errors["keyword"] = str(exc)

    this_block = _block(this_rows)
    last_block = _block(last_rows)

    # 每个父体单独留一份，供报告按父体拆分广告
    by_parent: Dict[str, Any] = {}
    for parent in product.get("parents") or []:
        asin = str(parent.get("asin") or "")
        if not asin or f"{asin}-this" not in raw_rows:
            continue
        by_parent[asin] = {
            "this": _block([_map_perf(r) for r in raw_rows.get(f"{asin}-this") or []]),
            "last": _block([_map_perf(r) for r in raw_rows.get(f"{asin}-last") or []]),
        }
    result = {
        "source": "lingxing",
        "week_start": this_start,
        "this": this_block,
        "last": last_block,
        "campaigns": campaigns,
        "keywords": keywords,
        "profit": this_block["aggregate"].get("profit", 0.0),
        "errors": errors,
        "shops": [{"sid": s.get("sid"), "profile_id": s.get("profile_id"), "alias": s.get("alias")} for s in shops],
        "by_parent": by_parent,
    }
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "raw" / "lingxing-performance.json", raw_rows)
    write_json(out_dir / "raw" / "lingxing.json", result)
    return result

def collect(product: Dict[str, Any], week_start: dt.date, out_dir: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    """Gateway (help/search/action) or legacy direct-tool collector."""
    if is_gateway():
        return _collect_gateway(product, week_start, out_dir, only)
    return _collect_direct(product, week_start, out_dir, only)
