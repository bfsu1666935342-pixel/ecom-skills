#!/usr/bin/env python3
"""备货计划：从领星取 SKU 级销量与库存，按半月汇总，算日销/月总/可售天数/建议备货。

用法：
  python restock.py run      # 抓数 + 出报告
  python restock.py collect  # 只抓数
  python restock.py build    # 只用已有 raw 出报告
  python restock.py doctor   # 检查连通性

只读：全部走领星的查询接口，不写任何平台数据。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS = Path(__file__).resolve().parent          # <skill>/scripts
ROOT = SCRIPTS.parent                              # <skill>
SKILLS = ROOT.parent                               # 技能根目录
DATA = ROOT / "data"
REPORT_DIR = ROOT / "reports"
# 产品清单与周报共用（SPU / 站点 / 店铺 / 父体 ASIN 都在那里面维护）
WEEKLY_CONFIG = SKILLS / "amazon-weekly-report" / "config" / "products.json"
OWN_CONFIG = ROOT / "config" / "products.json"

# 备货参数（可在 config/settings.json 覆盖）
DEFAULTS = {
    "lead_time_days": 45,        # 下单到入仓（采购 + 头程）
    "safety_days": 30,           # 安全库存天数
    "sale_window_days": 30,      # 日销按最近多少天平均
    "half_month_count": 3,       # 展示最近几个半月
}


# ---------------------------------------------------------------- 配置与工具
def load_products() -> List[Dict[str, Any]]:
    for path in (OWN_CONFIG, WEEKLY_CONFIG):
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            return [p for p in doc.get("products", []) if p.get("enabled", True)]
    return []


def load_settings() -> Dict[str, Any]:
    path = ROOT / "config" / "settings.json"
    if path.exists():
        try:
            return {**DEFAULTS, **json.loads(path.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            pass
    return dict(DEFAULTS)


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    # 技能目录下的 .env
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


class MCPError(RuntimeError):
    pass


class Client:
    """最小 MCP 客户端：initialize → tools/call(action)"""

    def __init__(self) -> None:
        self.url = env("LINGXING_MCP_URL", "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp")
        self.key = env("LINGXING_MCP_KEY")
        self.session = ""
        self.timeout = 90
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
        # 兼容 SSE
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
        blocks = result.get("content") or []
        text = ""
        for block in blocks:
            if block.get("type") == "text":
                text += block.get("text") or ""
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
    """剥层取 list"""
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


def num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def money(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"


def pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def half_of(day: dt.date) -> Tuple[str, int, int]:
    """返回 (半月标签, 年, 月) 以及该半月天数"""
    return (f"{day.year}-{day.month:02d}-上" if day.day <= 15 else f"{day.year}-{day.month:02d}-下")


# ---------------------------------------------------------------- 采集
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
    summary: str = "sku",
    length: int = 200,
    max_pages: int = 12,
    search_field: str = "",
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
            "summary_field": summary,
            "summary_field_level1": summary,
            "sids": sids,
            "currency_code": "USD",
            "length": length,
            "offset": offset,
            "sort_field": "volume",
            "sort_type": "desc",
        }
        # 服务端过滤，能少翻很多页（用父体 ASIN，比 SPU 稳）
        if search_field and search_values:
            params["search_field"] = search_field
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
                        client_init = getattr(client, "init", None)
                        if callable(client_init):
                            client_init()
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


def spu_of(row: Dict[str, Any]) -> str:
    names = row.get("spu_spu_names") or []
    if isinstance(names, list) and names:
        first = names[0] or {}
        return str(first.get("spu") or first.get("spu_name") or "").strip()
    return str(row.get("spu") or "").strip()


def stock_of(row: Dict[str, Any]) -> Dict[str, float]:
    avail = row.get("available_inventory")
    if isinstance(avail, dict):
        fba = num(avail.get("available_inventory")) or num(avail.get("afn_fulfillable_quantity"))
        reserved = num(avail.get("afn_reserved_quantity"))
    else:
        fba = num(row.get("afn_fulfillable_quantity"))
        reserved = num(row.get("afn_reserved_quantity"))
    inbound = num(row.get("total_inbound")) or num(row.get("afn_total_inbound"))
    return {
        "fba": fba,
        "reserved": reserved,
        "inbound": inbound,
        "shipped": num(row.get("afn_inbound_shipped_quantity")),
        "working": num(row.get("afn_inbound_working_quantity")),
    }


def collect_product(client: Client, product: Dict[str, Any], settings: Dict[str, Any], today: dt.date) -> Dict[str, Any]:
    spu = str(product.get("spu") or "")
    site = str(product.get("site") or "US").upper()
    shops = shops_for(client, site, product.get("store"))
    if not shops:
        raise MCPError(f"领星没有 {site} 的授权店铺")
    sids = ",".join(str(s.get("sid")) for s in shops if s.get("sid"))
    store_label = "、".join(str(s.get("alias") or s.get("sid")) for s in shops[:3])
    print(f"  店铺：{len(shops)} 个（{store_label}{'…' if len(shops) > 3 else ''}）", flush=True)

    window = int(settings.get("sale_window_days") or 30)
    span = max(window + 40, 70)
    day_start = (today - dt.timedelta(days=span)).isoformat()
    day_end = today.isoformat()
    print(f"  日销明细：{day_start} ~ {day_end}", flush=True)
    parent_asins = [str((p or {}).get("asin") or "").strip().upper() for p in product.get("parents") or []]
    parent_asins = [x for x in parent_asins if x]
    daily = fetch_rows(
        client, sids, day_start, day_end, "day",
        max_pages=15, search_field="parent_asin" if parent_asins else "", search_values=parent_asins,
    )
    print(f"    日粒度 {len(daily)} 行", flush=True)

    # 历年同月（今年、去年、前年）
    months: Dict[str, Dict[str, Any]] = {}
    for back in (2, 1, 0):
        year = today.year - back
        if year < 2020:
            continue
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        print(f"  历年同月：{year}", flush=True)
        rows = fetch_rows(
            client, sids, start, end, "month",
            max_pages=6, search_field="parent_asin" if parent_asins else "", search_values=parent_asins,
        )
        hit = [r for r in rows if str(r.get("rdate") or "") == f"{year}-{today.month:02d}"]
        total = sum(num(r.get("volume")) for r in hit)
        per_sku: Dict[str, float] = {}
        for r in hit:
            k = sku_of(r)
            if k:
                per_sku[k] = per_sku.get(k, 0.0) + num(r.get("volume"))
        months[str(year)] = {"units": total, "skus": per_sku, "rows": len(hit)}
        print(f"    {year}-{today.month:02d}：{len(hit)} 行，{total:,.0f} 件", flush=True)

    # 库存快照：从日粒度里每 SKU 取最后一天
    stock: Dict[str, Dict[str, Any]] = {}
    latest: Dict[str, str] = {}
    for row in daily:
        k = sku_of(row)
        if not k:
            continue
        day = str(row.get("rdate") or "")[:10]
        if k not in latest or day >= latest[k]:
            latest[k] = day
            st = stock_of(row)
            st["date"] = day
            st["asin"] = str(row.get("asin") or "")
            st["title"] = str(row.get("item_name") or row.get("local_name") or "")
            stock[k] = st

    # 只保留本产品的 SKU（同一店铺可能还有别的 SPU）
    daily = [r for r in daily if spu_of(r) == spu or not spu_of(r)]
    bundle = {
        "spu": spu,
        "site": site,
        "title": str(product.get("title") or spu),
        "store": product.get("store"),
        "shops": [{"sid": s.get("sid"), "alias": s.get("alias")} for s in shops],
        "today": today.isoformat(),
        "settings": settings,
        "daily": [
            {
                "date": str(r.get("rdate") or "")[:10],
                "sku": sku_of(r),
                "spu": spu_of(r),
                "units": num(r.get("volume")),
                "revenue": num(r.get("amount")),
            }
            for r in daily
            if sku_of(r)
        ],
        "stock": stock,
        "same_month": months,
    }
    return bundle


def cmd_collect(products: List[Dict[str, Any]], settings: Dict[str, Any], today: dt.date) -> List[Path]:
    client = Client()
    client.init()
    DATA.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for product in products:
        spu = str(product.get("spu") or "")
        print(f"- {spu} · {product.get('site','US')}", flush=True)
        bundle = collect_product(client, product, settings, today)
        path = DATA / f"{spu}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


# ---------------------------------------------------------------- 计算
def half_month_buckets(daily: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    """把日销按自然半月汇总，返回最近 count 个半月（新的在前）"""
    bucket: Dict[str, Dict[str, Any]] = {}
    for row in daily:
        day = row.get("date") or ""
        try:
            d = dt.date.fromisoformat(day)
        except ValueError:
            continue
        label = f"{d.year}-{d.month:02d}-上" if d.day <= 15 else f"{d.year}-{d.month:02d}-下"
        item = bucket.setdefault(label, {"label": label, "units": 0.0, "days": set()})
        item["units"] += num(row.get("units"))
        item["days"].add(day)
    out = []
    for label in sorted(bucket.keys(), reverse=True)[:count]:
        item = bucket[label]
        days = len(item["days"]) or 15
        out.append({"label": label, "units": item["units"], "days": days})
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

    # 本月至今 + 按日销推算全月
    month_prefix = f"{today.year}-{today.month:02d}"
    mtd = sum(num(r.get("units")) for r in daily if str(r.get("date", "")).startswith(month_prefix))
    days_in_month = (dt.date(today.year + (today.month == 12), (today.month % 12) + 1, 1) - dt.timedelta(days=1)).day
    month_est = per_day * days_in_month

    fba = num(stock.get("fba"))
    inbound = num(stock.get("inbound"))
    cover_days = (fba / per_day) if per_day > 0 else None
    # 建议备货：覆盖交期 + 安全库存，减掉现有与在途
    need = per_day * (lead + safety) - fba - inbound
    suggest = max(0.0, need)

    hist = {}
    for year, item in (same_month or {}).items():
        hist[year] = num(item.get("units"))
    this_year = hist.get(str(today.year), 0.0)
    last_year = hist.get(str(today.year - 1), 0.0)
    yoy = (this_year / last_year - 1) if last_year else None

    return {
        "sku": sku,
        "per_day": per_day,
        "window_units": window_units,
        "mtd": mtd,
        "month_est": month_est,
        "fba": fba,
        "inbound": inbound,
        "cover_days": cover_days,
        "suggest": suggest,
        "same_month": hist,
        "yoy": yoy,
        "asin": stock.get("asin") or "",
        "title": stock.get("title") or "",
        "stock_date": stock.get("date") or "",
        "risk": ("断货" if (cover_days is not None and cover_days < lead * 0.6)
                 else "偏紧" if (cover_days is not None and cover_days < lead)
                 else "正常"),
    }


def build_bundle(path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(bundle["today"])
    daily = bundle.get("daily") or []
    per_sku: Dict[str, List[Dict[str, Any]]] = {}
    for row in daily:
        per_sku.setdefault(row["sku"], []).append(row)

    skus = []
    for sku, rows in per_sku.items():
        skus.append(compute_sku(sku, rows, (bundle.get("stock") or {}).get(sku) or {}, bundle.get("same_month") or {}, settings, today))
    skus.sort(key=lambda x: x["per_day"], reverse=True)

    spu_units_window = sum(s["window_units"] for s in skus)
    window = int(settings.get("sale_window_days") or 30)
    spu_per_day = spu_units_window / window if window else 0.0
    spu_stock = sum(s["fba"] for s in skus)
    spu_inbound = sum(s["inbound"] for s in skus)
    spu_cover = (spu_stock / spu_per_day) if spu_per_day > 0 else None
    spu_suggest = sum(s["suggest"] for s in skus)

    hist = {}
    for year, item in (bundle.get("same_month") or {}).items():
        hist[year] = num(item.get("units"))
    this_year = hist.get(str(today.year), 0.0)
    last_year = hist.get(str(today.year - 1), 0.0)

    return {
        "spu": bundle["spu"],
        "site": bundle.get("site", "US"),
        "title": bundle.get("title") or bundle["spu"],
        "today": today.isoformat(),
        "skus": skus,
        "spu": bundle["spu"],
        "spu_metrics": {
            "per_day": spu_per_day,
            "window_units": spu_units_window,
            "fba": spu_stock,
            "inbound": spu_inbound,
            "cover_days": spu_cover,
            "suggest": spu_suggest,
            "same_month": hist,
            "this_year": this_year,
            "last_year": last_year,
            "yoy": (this_year / last_year - 1) if last_year else None,
        },
        "halves": half_month_buckets(daily, int(settings.get("half_month_count") or 3)),
    }


# ---------------------------------------------------------------- 渲染
CSS = """
:root { --ink:#1a1a1a; --muted:#666; --line:#e5e6eb; --bg:#f7f8fa; --warn:#b45309; --danger:#b91c1c; }
* { box-sizing: border-box; }
body { margin:0; padding:36px 28px 80px; font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:var(--ink); background:#fff; }
main { max-width: 980px; margin: 0 auto; }
h1 { font-size:26px; margin:0 0 6px; letter-spacing:-0.2px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:26px; }
h2 { font-size:19px; margin:38px 0 10px; padding-top:18px; border-top:1px solid var(--line); }
h3 { font-size:15px; margin:24px 0 8px; }
table { border-collapse: collapse; width:100%; font-size:13px; margin:8px 0 4px; }
th { text-align:left; font-weight:600; color:var(--muted); background:var(--bg); padding:8px 10px; border-bottom:1px solid #cfd3d9; white-space:nowrap; }
td { padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.num, th.num { text-align:right; font-variant-numeric: tabular-nums; }
.note { color:var(--muted); font-size:12px; margin:6px 0 0; }
.tag { display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px; background:var(--bg); color:var(--muted); }
.tag.danger { color:var(--danger); background:#fdecec; }
.tag.warn { color:var(--warn); background:#fdf3e3; }
.cards { display:flex; gap:12px; flex-wrap:wrap; margin:14px 0 6px; }
.card { flex:1 1 150px; border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.card .k { font-size:11px; color:var(--muted); }
.card .v { font-size:20px; font-weight:600; margin-top:2px; font-variant-numeric: tabular-nums; }
"""


def esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def table(headers: List[str], rows: List[List[str]], num_cols: Optional[List[int]] = None) -> str:
    num_cols = num_cols or []
    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}">{esc(h)}</th>' for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render(data: Dict[str, Any], settings: Dict[str, Any]) -> str:
    parts: List[str] = []
    total_per_day = sum(d["spu_metrics"]["per_day"] for d in data["products"])
    total_suggest = sum(d["spu_metrics"]["suggest"] for d in data["products"])
    risk_n = sum(1 for d in data["products"] for s in d["skus"] if s["risk"] == "断货")

    parts.append(f"<h1>备货计划 · {data['today']}</h1>")
    parts.append(
        '<div class="sub">'
        f"{len(data['products'])} 个 SPU · 日销按最近 {settings.get('sale_window_days')} 天平均 · "
        f"交期 {settings.get('lead_time_days')} 天 + 安全库存 {settings.get('safety_days')} 天"
        "</div>"
    )

    parts.append('<div class="cards">')
    parts.append(f'<div class="card"><div class="k">整体日销</div><div class="v">{total_per_day:,.1f} 件</div></div>')
    parts.append(f'<div class="card"><div class="k">建议备货合计</div><div class="v">{total_suggest:,.0f} 件</div></div>')
    parts.append(f'<div class="card"><div class="k">断货风险 SKU</div><div class="v">{risk_n} 个</div></div>')
    parts.append("</div>")

    overview_rows = []
    for d in data["products"]:
        m = d["spu_metrics"]
        yoy = f"{m['yoy']*100:+.0f}%" if m.get("yoy") is not None else "—"
        overview_rows.append([
            esc(d["spu"]),
            f"{m['per_day']:,.1f}",
            f"{m['fba']:,.0f}",
            f"{m['inbound']:,.0f}",
            f"{m['cover_days']:,.0f} 天" if m.get("cover_days") is not None else "—",
            f"{m['suggest']:,.0f}",
            yoy,
        ])
    parts.append("<h2>总览</h2>")
    parts.append(table(["SPU", "日销", "FBA 可售", "在途", "可售天数", "建议备货", "同月同比"],
                       overview_rows, [1, 2, 3, 4, 5, 6]))

    for d in data["products"]:
        m = d["spu_metrics"]
        parts.append(f"<h2>{esc(d['spu'])} · {esc(str(d.get('title') or '')[:40])}</h2>")

        # 半月销量
        halves = d.get("halves") or []
        if halves:
            parts.append("<h3>半月销量</h3>")
            rows = [[esc(h["label"]), f"{h['units']:,.0f}", f"{h['units']/h['days']:,.1f}"] for h in halves]
            parts.append(table(["半月", "销量", "日均"], rows, [1, 2]))
            parts.append('<p class="note">按自然半月统计（1–15 / 16–月末），日均 = 销量 ÷ 该半月已有天数。</p>')

        # 历年同月
        hist = m.get("same_month") or {}
        if hist:
            parts.append(f"<h3>历年 {data['today'][5:7]} 月销量</h3>")
            rows = []
            for year in sorted(hist.keys(), reverse=True):
                units = hist[year]
                prev = hist.get(str(int(year) - 1))
                yoy = f"{(units/prev-1)*100:+.0f}%" if prev else "—"
                rows.append([f"{year} 年 {data['today'][5:7]} 月", f"{units:,.0f}", yoy])
            parts.append(table(["月份", "销量", "同比"], rows, [1, 2]))
            parts.append('<p class="note">往年数据只统计到该月同一时间点的完整月度值，不含当月未结束部分。</p>')

        # SKU 明细
        parts.append("<h3>SKU 备货</h3>")
        rows = []
        for s in d["skus"]:
            risk = f'<span class="tag {("danger" if s["risk"]=="断货" else "warn" if s["risk"]=="偏紧" else "")}">{esc(s["risk"])}</span>'
            rows.append([
                esc(s["sku"]),
                f"{s['per_day']:,.1f}",
                f"{s['mtd']:,.0f}",
                f"{s['month_est']:,.0f}",
                f"{s['fba']:,.0f}",
                f"{s['inbound']:,.0f}",
                f"{s['cover_days']:,.0f} 天" if s.get("cover_days") is not None else "—",
                f"{s['suggest']:,.0f}",
                risk,
            ])
        parts.append(table(["SKU", "日销", "本月已售", "本月推算", "FBA", "在途", "可售天数", "建议备货", "风险"],
                           rows, [1, 2, 3, 4, 5, 6, 7]))
        parts.append(
            '<p class="note">建议备货 = 日销 ×（交期 + 安全天数）− FBA − 在途；负数按 0 处理。'
            "可售天数 = FBA ÷ 日销。库存快照日期以最后一次日粒度数据为准。</p>"
        )

    gaps = data.get("gaps") or []
    if gaps:
        parts.append("<h2>数据缺口</h2><ul>")
        for gap in gaps:
            parts.append(f"<li>{esc(gap)}</li>")
        parts.append("</ul>")

    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
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
            gaps.append(f"{bundle['spu']} 没有 SKU 级销量（可能该店铺无数据）")
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
    client = Client()
    client.init()
    shops = shops_for(client, "US")
    print(f"领星连通 OK  US 店铺 {len(shops)} 个")
    if shops:
        sid = str(shops[0].get("sid"))
        today = dt.date.today()
        rows = fetch_rows(client, sid, (today - dt.timedelta(days=7)).isoformat(), today.isoformat(), "day", max_pages=1)
        print(f"抽样店铺：{shops[0].get('alias')}  近 7 天 SKU 明细 {len(rows)} 行")
        if rows:
            r = rows[0]
            print(f"  样例：sku={r.get('sku')} spu={spu_of(r)} 销量={r.get('volume')} 库存={stock_of(r).get('fba')}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    settings = load_settings()
    if cmd == "doctor":
        return cmd_doctor()

    products = load_products()
    if not products:
        raise SystemExit("没有找到产品配置（config/products.json 或周报的 products.json）")
    # 可选：只跑指定的 SPU（调试用）python restock.py run LS-66D38
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
