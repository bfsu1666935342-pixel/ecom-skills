#!/usr/bin/env python3
"""备货计划：销量来自领星（SKU 日销），库存来自本地表格（可选）。

用法：
  python restock.py run      # 抓销量 + 出报告
  python restock.py build    # 只用已有 raw 出报告
  python restock.py doctor   # 检查连通性

库存：放在 config/inventory.csv（或 .json），没有就留空，不猜。
  表头：sku,on_hand,in_transit,in_production
  也认中文表头：SKU,在库,在途,在产
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
SKILLS = ROOT.parent
DATA = ROOT / "data"
REPORT_DIR = ROOT / "reports"
CONFIG = ROOT / "config"
WEEKLY_CONFIG = SKILLS / "amazon-weekly-report" / "config" / "products.json"
OWN_CONFIG = CONFIG / "products.json"

DEFAULTS = {
    "lead_time_days": 45,
    "safety_days": 30,
    "sale_window_days": 30,
    "half_month_count": 3,
    "history_years": 3,
}


# ---------------------------------------------------------------- 基础工具
def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for env_file in (ROOT / ".env", SKILLS / ".env", SKILLS / "amazon-weekly-report" / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    return default


def num(v: Any) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def money(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"


def pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def load_products() -> List[Dict[str, Any]]:
    for path in (OWN_CONFIG, WEEKLY_CONFIG):
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            return [p for p in doc.get("products", []) if p.get("enabled", True)]
    return []


def load_settings() -> Dict[str, Any]:
    path = CONFIG / "settings.json"
    if path.exists():
        try:
            return {**DEFAULTS, **json.loads(path.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            pass
    return dict(DEFAULTS)


class MCPError(RuntimeError):
    pass


class Client:
    def __init__(self) -> None:
        self.url = env("LINGXING_MCP_URL", "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp")
        self.key = env("LINGXING_MCP_KEY")
        self.session = ""
        self.timeout = 120
        if not self.key:
            raise MCPError("没有领星 Key：到工作台「数据源」配好领星，或在 .env 里填 LINGXING_MCP_KEY")

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("X-Mcp-Key", self.key)
        if self.session:
            req.add_header("mcp-session-id", self.session)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session = sid
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise MCPError(f"领星 HTTP {exc.code}: {exc.read()[:200]!r}") from exc
        except Exception as exc:  # noqa: BLE001
            raise MCPError(f"领星请求失败：{exc}") from exc
        if raw.lstrip().startswith("event:") or "\ndata:" in raw:
            for line in raw.splitlines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    break
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPError(f"领星返回非 JSON：{raw[:160]}") from exc

    def init(self) -> None:
        self._post({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "restock", "version": "1"}},
        })
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except MCPError:
            pass

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        doc = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}})
        result = doc.get("result") or {}
        text = "".join(b.get("text") or "" for b in (result.get("content") or []) if b.get("type") == "text")
        if result.get("isError"):
            raise MCPError("领星工具返回错误：" + (text or "")[:200])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    def action(self, tool_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        doc = self.call("action", {"toolId": tool_id, "params": params})
        if not isinstance(doc, dict) or doc.get("code") not in (1, None):
            raise MCPError(f"领星 {tool_id} 失败：{str(doc)[:200]}")
        return doc.get("data") or {}


def rows_of(payload: Any) -> List[Dict[str, Any]]:
    cur = payload
    for _ in range(6):
        if isinstance(cur, list):
            return [r for r in cur if isinstance(r, dict)]
        if not isinstance(cur, dict):
            return []
        if isinstance(cur.get("list"), list):
            return [r for r in cur["list"] if isinstance(r, dict)]
        cur = cur.get("data")
    return []


# ---------------------------------------------------------------- 库存表
STOCK_ALIASES = {
    "sku": ("sku", "msku", "SKU", "MSKU", "商品sku"),
    "on_hand": ("on_hand", "库存", "在库", "可售", "fba", "FBA", "in_stock"),
    "in_transit": ("in_transit", "在途", "运输中", "shipping"),
    "in_production": ("in_production", "在产", "生产中", "producing"),
}


def load_inventory() -> Dict[str, Dict[str, float]]:
    """读 config/inventory.csv 或 inventory.json；没有就返回空。"""
    out: Dict[str, Dict[str, float]] = {}

    csv_path = CONFIG / "inventory.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            heads = {h.strip(): h for h in (reader.fieldnames or [])}
            def pick(key: str) -> Optional[str]:
                for alias in STOCK_ALIASES[key]:
                    for head, original in heads.items():
                        if head == alias or head.lower() == alias.lower():
                            return original
                return None
            col_sku, col_on = pick("sku"), pick("on_hand")
            col_tr, col_pr = pick("in_transit"), pick("in_production")
            if col_sku:
                for row in reader:
                    sku = str(row.get(col_sku) or "").strip()
                    if not sku:
                        continue
                    out[sku.upper()] = {
                        "on_hand": num(row.get(col_on)) if col_on else 0.0,
                        "in_transit": num(row.get(col_tr)) if col_tr else 0.0,
                        "in_production": num(row.get(col_pr)) if col_pr else 0.0,
                    }
        return out

    json_path = CONFIG / "inventory.json"
    if json_path.exists():
        try:
            doc = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return out
        items = doc.get("items") if isinstance(doc, dict) else doc
        for row in items or []:
            sku = str((row or {}).get("sku") or "").strip()
            if not sku:
                continue
            out[sku.upper()] = {
                "on_hand": num(row.get("on_hand") or row.get("在库")),
                "in_transit": num(row.get("in_transit") or row.get("在途")),
                "in_production": num(row.get("in_production") or row.get("在产")),
            }
    return out


# ---------------------------------------------------------------- 采集（只取销量）
def shops_for(client: Client, site: str, store: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    data = client.action("ad_auth_shops", {})
    rows = data.get("data") or []
    site = (site or "US").upper()
    pool = [r for r in rows if str(r.get("country", "")).upper() == site]
    if not store or not isinstance(store, dict):
        return pool
    sid = store.get("sid")
    alias = str(store.get("alias") or "").strip()
    for r in pool:
        if sid and str(r.get("sid")) == str(sid):
            return [r]
    for r in pool:
        if alias and str(r.get("alias") or "").strip() == alias:
            return [r]
    return pool


def fetch_rows(
    client: Client,
    sids: str,
    start: str,
    end: str,
    view: str,
    length: int = 200,
    max_pages: int = 15,
    search_values: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        params = {
            "start_date": start,
            "end_date": end,
            "date_type": "purchase",
            "date_view_type": view,
            "date_view_order_type": 1 if view != "day" else 0,
            "summary_field": "sku",
            "summary_field_level1": "sku",
            "sids": sids,
            "currency_code": "USD",
            "length": length,
            "offset": offset,
            "sort_field": "volume",
            "sort_type": "desc",
        }
        if search_values:
            params["search_field"] = "parent_asin"
            params["search_value"] = list(search_values)
        payload = None
        for attempt in (1, 2):
            try:
                payload = client.action("query_product_performance_asin_lists", params)
                break
            except MCPError as exc:
                if attempt == 2:
                    print(f"    ! 取数失败（{start}~{end} {view}）：{exc}", flush=True)
                else:
                    try:
                        client.init()
                    except Exception:  # noqa: BLE001
                        pass
        if payload is None:
            break
        rows = rows_of(payload)
        if not rows:
            break
        out.extend(rows)
        if len(rows) < length:
            break
        offset += length
    return out


def sku_of(row: Dict[str, Any]) -> str:
    return str(row.get("sku") or row.get("msku") or "").strip()


def collect_product(client: Client, product: Dict[str, Any], settings: Dict[str, Any], today: dt.date, inventory: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    spu = str(product.get("spu") or "")
    site = str(product.get("site") or "US").upper()
    shops = shops_for(client, site, product.get("store"))
    if not shops:
        raise MCPError(f"领星没有 {site} 的授权店铺")
    sids = ",".join(str(s.get("sid")) for s in shops if s.get("sid"))
    store_label = "、".join(str(s.get("alias") or s.get("sid")) for s in shops[:3])
    print(f"  店铺：{len(shops)} 个（{store_label}{'…' if len(shops) > 3 else ''}）", flush=True)

    parents = sorted({str((p or {}).get("asin") or "").strip().upper() for p in product.get("parents") or []} - {""})

    window = int(settings.get("sale_window_days") or 30)
    span = max(window + 45, 80)
    start = (today - dt.timedelta(days=span)).isoformat()
    print(f"  销量明细：{start} ~ {today.isoformat()}", flush=True)
    daily_rows = fetch_rows(client, sids, start, today.isoformat(), "day", max_pages=15, search_values=parents)
    daily = []
    for r in daily_rows:
        sku = sku_of(r)
        if not sku:
            continue
        daily.append({
            "date": str(r.get("rdate") or "")[:10],
            "sku": sku,
            "units": num(r.get("volume")),
            "revenue": num(r.get("amount")),
        })
    print(f"    日粒度 {len(daily)} 行，SKU {len({d['sku'] for d in daily})} 个", flush=True)

    months: Dict[str, Dict[str, Any]] = {}
    for back in range(int(settings.get("history_years") or 3)):
        year = today.year - back
        if year < 2020:
            continue
        print(f"  历年同月：{year}", flush=True)
        mrows = fetch_rows(client, sids, f"{year}-01-01", f"{year}-12-31", "month", max_pages=6, search_values=parents)
        hit = [r for r in mrows if str(r.get("rdate") or "") == f"{year}-{today.month:02d}"]
        per_sku: Dict[str, float] = {}
        for r in hit:
            key = sku_of(r)
            if key:
                per_sku[key] = per_sku.get(key, 0.0) + num(r.get("volume"))
        months[str(year)] = {"units": sum(per_sku.values()), "skus": per_sku, "rows": len(hit)}
        print(f"    {year}-{today.month:02d}：{len(hit)} 行，{months[str(year)]['units']:,.0f} 件", flush=True)

    skus = sorted({d["sku"] for d in daily})
    stock_rows = []
    for sku in skus:
        item = inventory.get(sku.upper()) or {}
        stock_rows.append({
            "sku": sku,
            "on_hand": num(item.get("on_hand")),
            "in_transit": num(item.get("in_transit")),
            "in_production": num(item.get("in_production")),
            "has_stock": bool(item),
        })
    have = sum(1 for s in stock_rows if s["has_stock"])
    print(f"  库存表：{have}/{len(stock_rows)} 个 SKU 有数据", flush=True)

    return {
        "spu": spu,
        "site": site,
        "title": str(product.get("title") or spu),
        "store": product.get("store"),
        "shops": [{"sid": s.get("sid"), "alias": s.get("alias")} for s in shops],
        "today": today.isoformat(),
        "settings": settings,
        "daily": daily,
        "same_month": months,
        "stock": stock_rows,
    }


def cmd_collect(products: List[Dict[str, Any]], settings: Dict[str, Any], today: dt.date) -> List[Path]:
    client = Client()
    client.init()
    inventory = load_inventory()
    DATA.mkdir(parents=True, exist_ok=True)
    written = []
    for product in products:
        spu = str(product.get("spu") or "")
        print(f"- {spu} · {product.get('site','US')}", flush=True)
        bundle = collect_product(client, product, settings, today, inventory)
        path = DATA / f"{spu}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written



# ---------------------------------------------------------------- 计算
def half_key(day: dt.date) -> Tuple[str, dt.date, dt.date]:
    """自然半月：1–15 / 16–月末，返回 (标签, 起, 止)"""
    if day.day <= 15:
        return (f"{day.year}-{day.month:02d}-上", dt.date(day.year, day.month, 1), dt.date(day.year, day.month, 15))
    last = (dt.date(day.year + (day.month == 12), (day.month % 12) + 1, 1) - dt.timedelta(days=1)).day
    return (f"{day.year}-{day.month:02d}-下", dt.date(day.year, day.month, 16), dt.date(day.year, day.month, last))


def halves_of(daily: List[Dict[str, Any]], today: dt.date, count: int) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in daily:
        try:
            day = dt.date.fromisoformat(row["date"])
        except (KeyError, ValueError):
            continue
        label, _, _ = half_key(day)
        item = buckets.setdefault(label, {"label": label, "units": 0.0, "days": set()})
        item["units"] += num(row.get("units"))
        item["days"].add(row["date"])
    # 补上当前半月（可能还没销量）
    cur_label, _, _ = half_key(today)
    buckets.setdefault(cur_label, {"label": cur_label, "units": 0.0, "days": set()})
    labels = sorted(buckets.keys(), reverse=True)[:count]
    out = []
    for label in labels:
        item = buckets[label]
        days = len(item["days"]) or 1
        out.append({"label": label, "units": item["units"], "days": days, "per_day": item["units"] / days})
    return out


def compute_sku(
    sku: str,
    daily: List[Dict[str, Any]],
    stock: Dict[str, Any],
    same_month: Dict[str, Any],
    settings: Dict[str, Any],
    today: dt.date,
) -> Dict[str, Any]:
    window = int(settings.get("sale_window_days") or 30)
    lead = int(settings.get("lead_time_days") or 45)
    safety = int(settings.get("safety_days") or 30)

    since = (today - dt.timedelta(days=window)).isoformat()
    window_units = sum(num(r.get("units")) for r in daily if r.get("date", "") >= since)
    per_day = window_units / window if window else 0.0

    # 当前自然月：已售 + 按日销推算全月
    m_start = dt.date(today.year, today.month, 1)
    mtd = sum(num(r.get("units")) for r in daily if r.get("date", "") >= m_start.isoformat())
    days_in_month = (dt.date(today.year + (today.month == 12), (today.month % 12) + 1, 1) - dt.timedelta(days=1)).day
    month_est = per_day * days_in_month

    # 当前自然半月
    _, h_start, h_end = half_key(today)
    half_units = sum(num(r.get("units")) for r in daily if h_start.isoformat() <= r.get("date", "") <= h_end.isoformat())

    on_hand = num(stock.get("on_hand"))
    in_transit = num(stock.get("in_transit"))
    in_prod = num(stock.get("in_production"))
    has_stock = bool(stock.get("has_stock"))

    cover_days = (on_hand / per_day) if (has_stock and per_day > 0) else None
    suggest = None
    if has_stock:
        suggest = max(0.0, per_day * (lead + safety) - on_hand - in_transit - in_prod)

    if not has_stock:
        risk = "待补库存"
    elif cover_days is not None and cover_days < lead * 0.6:
        risk = "断货"
    elif cover_days is not None and cover_days < lead:
        risk = "偏紧"
    else:
        risk = "正常"

    hist = {}
    for year, item in (same_month or {}).items():
        hist[year] = num(((item or {}).get("skus") or {}).get(sku))

    return {
        "sku": sku,
        "per_day": per_day,
        "half": half_units,
        "mtd": mtd,
        "month_est": month_est,
        "on_hand": on_hand,
        "in_transit": in_transit,
        "in_production": in_prod,
        "has_stock": has_stock,
        "cover_days": cover_days,
        "suggest": suggest,
        "same_month": hist,
        "risk": risk,
    }


def build_bundle(path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(bundle["today"])
    daily = bundle.get("daily") or []
    stock_map = {str(s.get("sku")): s for s in bundle.get("stock") or []}
    same_month = bundle.get("same_month") or {}

    per_sku: Dict[str, List[Dict[str, Any]]] = {}
    for row in daily:
        per_sku.setdefault(row["sku"], []).append(row)

    skus = []
    for sku, rows in per_sku.items():
        skus.append(compute_sku(sku, rows, stock_map.get(sku) or {}, same_month, settings, today))
    skus.sort(key=lambda x: x["per_day"], reverse=True)

    def total(key: str) -> Optional[float]:
        vals = [s[key] for s in skus if s.get(key) is not None]
        return sum(vals) if vals else None

    window = int(settings.get("sale_window_days") or 30)
    per_day = sum(s["per_day"] for s in skus)
    on_hand = total("on_hand") or 0.0
    in_transit = total("in_transit") or 0.0
    has_stock = any(s["has_stock"] for s in skus)
    cover = (on_hand / per_day) if (has_stock and per_day > 0) else None
    suggest_total = total("suggest")

    hist = {year: num((item or {}).get("units")) for year, item in same_month.items()}
    this_year = hist.get(str(today.year), 0.0)
    last_year = hist.get(str(today.year - 1), 0.0)

    return {
        "spu": bundle["spu"],
        "site": bundle.get("site", "US"),
        "title": bundle.get("title") or bundle["spu"],
        "today": today.isoformat(),
        "skus": skus,
        "halves": halves_of(daily, today, int(settings.get("half_month_count") or 3)),
        "spu_metrics": {
            "per_day": per_day,
            "half": sum(s["half"] for s in skus),
            "mtd": sum(s["mtd"] for s in skus),
            "month_est": sum(s["month_est"] for s in skus),
            "on_hand": on_hand,
            "in_transit": in_transit,
            "has_stock": has_stock,
            "cover_days": cover,
            "suggest": suggest_total,
            "same_month": hist,
            "this_year": this_year,
            "last_year": last_year,
            "yoy": (this_year / last_year - 1) if last_year else None,
        },
    }


# ---------------------------------------------------------------- 渲染
CSS = """
:root { --ink:#1a1a1a; --muted:#666; --line:#e5e6eb; --bg:#f7f8fa; --warn:#b45309; --danger:#b91c1c; --ok:#15803d; }
* { box-sizing: border-box; }
body { margin:0; padding:36px 28px 80px; font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:var(--ink); background:#fff; }
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size:26px; margin:0 0 6px; letter-spacing:-0.2px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:22px; }
h2 { font-size:19px; margin:38px 0 10px; padding-top:18px; border-top:1px solid var(--line); }
h3 { font-size:15px; margin:22px 0 8px; }
table { border-collapse: collapse; width:100%; font-size:13px; margin:8px 0 4px; }
th { text-align:left; font-weight:600; color:var(--muted); background:var(--bg); padding:8px 10px; border-bottom:1px solid #cfd3d9; white-space:nowrap; }
td { padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.num, th.num { text-align:right; font-variant-numeric: tabular-nums; }
.note { color:var(--muted); font-size:12px; margin:6px 0 0; }
.tag { display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px; background:var(--bg); color:var(--muted); }
.tag.danger { color:var(--danger); background:#fdecec; }
.tag.warn { color:var(--warn); background:#fdf3e3; }
.tag.ok { color:var(--ok); background:#eefaf1; }
.cards { display:flex; gap:12px; flex-wrap:wrap; margin:14px 0 6px; }
.card { flex:1 1 150px; border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.card .k { font-size:11px; color:var(--muted); }
.card .v { font-size:20px; font-weight:600; margin-top:2px; font-variant-numeric: tabular-nums; }
.banner { border:1px solid #f0d9a8; background:#fdf7ea; color:#7a5a12; border-radius:10px; padding:10px 14px; font-size:13px; margin:10px 0 0; }
"""


def esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table(headers: List[str], rows: List[List[str]], num_cols: Optional[List[int]] = None) -> str:
    num_cols = num_cols or []
    head = "".join(f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>' for i, h in enumerate(headers))
    body = []
    for row in rows:
        cells = "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def fmt(v: Optional[float], digits: int = 0) -> str:
    return "—" if v is None else f"{v:,.{digits}f}"


def render(data: Dict[str, Any], settings: Dict[str, Any]) -> str:
    window = int(settings.get("sale_window_days") or 30)
    lead = int(settings.get("lead_time_days") or 45)
    safety = int(settings.get("safety_days") or 30)
    no_stock = not any(d["spu_metrics"]["has_stock"] for d in data["products"])

    parts: List[str] = []
    parts.append(f"<h1>备货计划 · {data['today']}</h1>")
    parts.append(
        '<div class="sub">'
        f"{len(data['products'])} 个 SPU · 销量来自领星（SKU 日销，近 {window} 天均值）· "
        f"交期 {lead} 天 + 安全库存 {safety} 天"
        "</div>"
    )
    if no_stock:
        parts.append(
            '<div class="banner">库存还没接：把在库/在途/在产填到 <code>config/inventory.csv</code>'
            "（表头 sku,on_hand,in_transit,in_production）再跑一次，可售天数与建议备货就会出来。</div>"
        )

    total_per_day = sum(d["spu_metrics"]["per_day"] for d in data["products"])
    total_suggest = sum(d["spu_metrics"].get("suggest") or 0 for d in data["products"])
    parts.append('<div class="cards">')
    parts.append(f'<div class="card"><div class="k">整体日销</div><div class="v">{total_per_day:,.1f} 件</div></div>')
    parts.append(f'<div class="card"><div class="k">建议备货合计</div><div class="v">{fmt(total_suggest) if not no_stock else "—"}</div></div>')
    parts.append(f'<div class="card"><div class="k">SKU 数</div><div class="v">{sum(len(d["skus"]) for d in data["products"])}</div></div>')
    parts.append("</div>")

    rows = []
    for d in data["products"]:
        m = d["spu_metrics"]
        yoy = f"{m['yoy']*100:+.0f}%" if m.get("yoy") is not None else "—"
        rows.append([
            esc(d["spu"]),
            fmt(m["per_day"], 1),
            fmt(m["half"]),
            fmt(m["month_est"]),
            fmt(m["on_hand"]) if m["has_stock"] else "—",
            fmt(m["in_transit"]) if m["has_stock"] else "—",
            f"{m['cover_days']:,.0f} 天" if m.get("cover_days") is not None else "—",
            fmt(m.get("suggest")) if m.get("suggest") is not None else "—",
            yoy,
        ])
    parts.append("<h2>总览</h2>")
    parts.append(table(
        ["SPU", "日销", "本半月已售", "本月推算", "在库", "在途", "可售天数", "建议备货", "同月同比"],
        rows, [1, 2, 3, 4, 5, 6, 7, 8],
    ))
    parts.append(
        '<p class="note">日销 = 近 %d 天销量 ÷ %d；本半月已售 = 当前自然半月（1–15 / 16–月末）累计；'
        "本月推算 = 日销 × 当月天数；可售天数 = 在库 ÷ 日销。</p>" % (window, window)
    )

    for d in data["products"]:
        m = d["spu_metrics"]
        ttl = str(d.get("title") or "")
        if ttl.startswith(d["spu"]):
            ttl = ttl[len(d["spu"]):].strip(" ·（）()")
        head = esc(d["spu"]) + ((" · " + esc(ttl[:40])) if ttl else "")
        parts.append(f"<h2>{head}</h2>")

        halves = d.get("halves") or []
        if halves:
            parts.append("<h3>半月销量</h3>")
            hrows = [[esc(h["label"]), fmt(h["units"]), fmt(h["per_day"], 1)] for h in halves]
            parts.append(table(["半月", "销量", "日均"], hrows, [1, 2]))
            parts.append('<p class="note">按自然半月统计；当前半月还没结束，日均按已有天数算。</p>')

        hist = m.get("same_month") or {}
        if any(hist.values()):
            parts.append(f"<h3>历年 {data['today'][5:7]} 月销量</h3>")
            rws = []
            for year in sorted(hist.keys(), reverse=True):
                units = hist[year]
                prev = hist.get(str(int(year) - 1))
                yoy = f"{(units/prev-1)*100:+.0f}%" if prev else "—"
                rws.append([f"{year} 年 {data['today'][5:7]} 月", fmt(units), yoy])
            parts.append(table(["月份", "销量", "同比"], rws, [1, 2]))

        parts.append("<h3>SKU 备货</h3>")
        srows = []
        for s in d["skus"]:
            cls = "danger" if s["risk"] == "断货" else "warn" if s["risk"] in ("偏紧", "待补库存") else "ok"
            srows.append([
                esc(s["sku"]),
                fmt(s["per_day"], 1),
                fmt(s["half"]),
                fmt(s["mtd"]),
                fmt(s["month_est"]),
                fmt(s["on_hand"]) if s["has_stock"] else "—",
                fmt(s["in_transit"]) if s["has_stock"] else "—",
                fmt(s["in_production"]) if s["has_stock"] else "—",
                f"{s['cover_days']:,.0f} 天" if s.get("cover_days") is not None else "—",
                fmt(s.get("suggest")) if s.get("suggest") is not None else "—",
                f'<span class="tag {cls}">{esc(s["risk"])}</span>',
            ])
        parts.append(table(
            ["SKU", "日销", "本半月", "本月已售", "本月推算", "在库", "在途", "在产", "可售天数", "建议备货", "风险"],
            srows, [1, 2, 3, 4, 5, 6, 7, 8, 9],
        ))
        parts.append(
            '<p class="note">建议备货 = 日销 ×（交期 + 安全天数）− 在库 − 在途 − 在产，负数按 0。'
            "库存来自 config/inventory.csv，没填的 SKU 标「待补库存」。</p>"
        )

    gaps = data.get("gaps") or []
    if gaps:
        parts.append("<h2>数据缺口</h2><ul>")
        for gap in gaps:
            parts.append(f"<li>{esc(gap)}</li>")
        parts.append("</ul>")

    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>备货计划 {data['today']}</title><style>{CSS}</style></head><body><main>"
        + "".join(parts)
        + "</main></body></html>"
    )


# ---------------------------------------------------------------- 命令
def cmd_build(settings: Dict[str, Any]) -> Path:
    products = []
    gaps: List[str] = []
    for path in sorted(DATA.glob("*.json")):
        try:
            bundle = build_bundle(path, settings)
        except Exception as exc:  # noqa: BLE001
            gaps.append(f"{path.stem} 计算失败：{exc}")
            continue
        if not bundle.get("skus"):
            gaps.append(f"{bundle['spu']} 没有 SKU 级销量数据")
        if not any(s["has_stock"] for s in bundle["skus"]):
            gaps.append(f"{bundle['spu']} 库存表里没有这些 SKU")
        products.append(bundle)
    if not products:
        raise SystemExit("没有可用数据，先跑 collect")
    data = {"today": dt.date.today().isoformat(), "products": products, "gaps": gaps}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"restock-{data['today']}.html"
    out.write_text(render(data, settings), encoding="utf-8")
    (REPORT_DIR / f"restock-{data['today']}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def cmd_doctor() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    client = Client()
    client.init()
    shops = shops_for(client, "US")
    print(f"领星连通 OK  US 店铺 {len(shops)} 个")
    inv = load_inventory()
    print(f"库存表：{len(inv)} 个 SKU（config/inventory.csv）" if inv else "库存表：还没提供（config/inventory.csv 不存在）")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    settings = load_settings()
    if cmd == "doctor":
        return cmd_doctor()

    products = load_products()
    if not products:
        raise SystemExit("没有找到产品配置（config/products.json 或周报的 products.json）")
    if len(sys.argv) > 2:
        wanted = {x.strip().upper() for x in sys.argv[2].split(",")}
        products = [p for p in products if str(p.get("spu", "")).upper() in wanted]
        if not products:
            raise SystemExit("指定的 SPU 没在配置里")
    if cmd in ("run", "collect"):
        cmd_collect(products, settings, dt.date.today())
    out = cmd_build(settings)
    print(f"报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
