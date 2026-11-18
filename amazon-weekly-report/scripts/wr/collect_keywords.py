"""Keyword / traffic structure collector.

Preferred source: SIF (exact traffic share, natural + ad positions).
Fallback: Sorftime ``product_traffic_terms`` (natural + ad positions, search volume).
Sorftime has no traffic-share field, so when it is the source the report uses an
explicitly labelled *estimate* (search volume x position weight) and says so.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mcp import MCPClient, MCPError, rows_from
from .util import env, first, load_config, load_env, num, pct, write_json, read_json

# Position weights used only for the Sorftime estimate. Reported as 估算口径.
_ORGANIC_WEIGHT = [
    (1, 4, 1.00), (1, 12, 0.30), (1, 24, 0.10), (1, 48, 0.04),
    (2, 48, 0.012), (3, 48, 0.004),
]
_AD_FACTOR = 0.60


def _weight(page: int, pos: int, ad: bool = False) -> float:
    if page <= 0 or pos <= 0:
        return 0.0
    base = 0.015
    for p, limit, value in _ORGANIC_WEIGHT:
        if page == p and pos <= limit:
            base = value
            break
    return base * (_AD_FACTOR if ad else 1.0)


def parse_position(text: Any) -> Tuple[int, int]:
    """'Page 1, Pos 34/48' -> (1, 34); '1-34' -> (1, 34); '34' -> (1, 34)."""
    s = str(text or "")
    match = re.search(r"page\s*(\d+).*?pos(?:ition)?\s*(\d+)", s, re.I)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)\s*[-/]\s*(\d+)", s)
    if match:
        return 1, int(match.group(1))
    match = re.search(r"\d+", s)
    if match:
        return 1, int(match.group(0))
    return 0, 0


def _sif_client(settings: Dict[str, Any]) -> Optional[MCPClient]:
    cfg = (settings.get("sources") or {}).get("sif") or {}
    url = env("SIF_MCP_URL", cfg.get("url", ""))
    if not url:
        return None
    key = env("SIF_MCP_KEY", "")
    return MCPClient(
        url,
        key,
        auth=cfg.get("auth", "query"),
        key_param=cfg.get("key_param", "secret-key"),
        label="SIF",
    )


def _sorftime_client(settings: Dict[str, Any]) -> MCPClient:
    cfg = (settings.get("sources") or {}).get("sorftime") or {}
    url = env("SORFTIME_MCP_URL", cfg.get("url", "https://mcp.sorftime.com"))
    key = env("SORFTIME_MCP_KEY", "")
    return MCPClient(
        url,
        key,
        auth=cfg.get("auth", "query"),
        key_param=cfg.get("key_param", "key"),
        label="Sorftime",
    )


def sif_tools() -> List[Dict[str, Any]]:
    settings = load_config("settings.json", {}) or {}
    c = _sif_client(settings)
    if not c:
        raise MCPError("SIF 未配置 URL")
    return c.list_tools()


SIF_TERM_ALIASES = {
    "keyword": ("keyword", "search_term", "term", "keyword_text", "word"),
    "search_volume": ("search_volume", "monthly_search_volume", "volume", "sv", "search_vol"),
    "traffic_share": ("traffic_share", "traffic_percentage", "traffic_ratio", "traffic_rate", "share", "traffic"),
    "organic_position": ("organic_position", "natural_position", "organic_rank", "natural_rank", "organic_pos", "rank"),
    "ad_position": ("ad_position", "ad_rank", "sponsored_position", "ad_pos", "ads_position"),
    "organic_page": ("organic_page", "natural_page", "page"),
    "ad_page": ("ad_page", "ads_page"),
}


def _sif_rows(payload: Any) -> List[Dict[str, Any]]:
    rows = rows_from(payload)
    if rows:
        return rows
    if isinstance(payload, dict):
        for key in ("keywords", "terms", "traffic_terms"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _from_sif(asin: str, site: str, settings: Dict[str, Any], week_end: str = "") -> Dict[str, Any]:
    c = _sif_client(settings)
    if not c:
        raise MCPError("SIF 未配置")
    tool = "market_get_asin_keyword_signals"
    payload_args = {
        "asin": asin,
        "country": site,
        "time_type": "week",
        "time_value": week_end or _last_sunday(),
        "pageNum": 1,
        "pageSize": 300,
    }
    terms: List[Dict[str, Any]] = []
    for page in range(1, 6):
        payload_args["pageNum"] = page
        payload = c.call(tool, payload_args)
        rows = (payload or {}).get("top_keywords") or []
        for row in rows:
            word = str(row.get("keyword") or "").strip()
            if not word:
                continue
            opage, opos = parse_rank(row.get("organic_rank"))
            spage, spos = parse_rank(row.get("sp_rank"))
            ad_label = _ad_label(row)
            terms.append({
                "keyword": word.lower(),
                "search_volume": num(row.get("search_volume")),
                "traffic_share": num(row.get("traffic_share")),
                "organic_page": opage,
                "organic_pos": opos,
                "ad_page": spage,
                "ad_pos": spos,
                "ad_label": ad_label,
                "natural_ratio": num(row.get("natural_ratio")),
                "dependency": str(row.get("traffic_dependency") or ""),
                "health": str(row.get("keyword_health") or ""),
                "cpc": num(row.get("cpc_median")),
            })
        pagination = (payload or {}).get("pagination") or {}
        if not pagination.get("hasMore"):
            break
    if not terms:
        raise MCPError("SIF 返回 0 条关键词")
    return {"source": "sif", "estimated_share": False, "tool": tool, "terms": terms}


def parse_rank(text: Any) -> Tuple[int, int]:
    """'p1,4/12' -> (1, 4); 'p3,32/48' -> (3, 32)."""
    s = str(text or "")
    match = re.search(r"p(\d+)\s*,\s*(\d+)", s, re.I)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def _ad_label(row: Dict[str, Any]) -> str:
    parts: List[str] = []
    spage, spos = parse_rank(row.get("sp_rank"))
    if spos:
        parts.append(f"SP{spage}-{spos}")
    for key, name in (("sb_rank", "SB"), ("sbv_rank", "SBV")):
        text = str(row.get(key) or "")
        if text:
            parts.append(name + ("顶" if "top" in text else "中"))
    return " / ".join(parts)


def _last_sunday() -> str:
    import datetime as dt
    today = dt.date.today()
    return (today - dt.timedelta(days=(today.weekday() + 1) % 7)).isoformat()


def _from_sorftime(asin: str, site: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    c = _sorftime_client(settings)
    payload = c.call("product_traffic_terms", {"asin": asin, "amz_site": site, "page": 1})
    rows = rows_from(payload)
    if not rows:
        text = payload.get("_text") if isinstance(payload, dict) else str(payload)
        raise MCPError(f"Sorftime 没有该 ASIN 的流量词（{text or '空'}）")
    terms = []
    for row in rows:
        word = str(first(row, ("keyword", "term", "search_term")) or "").strip()
        if not word:
            continue
        organic_text = first(row, ("latest_organic_position", "organic_position"))
        ad_text = first(row, ("latest_ad_position", "ad_position"))
        op, opos = parse_position(organic_text)
        ap, apos = parse_position(ad_text)
        terms.append({
            "keyword": word.lower(),
            "search_volume": num(first(row, ("monthly_search_volume", "search_volume", "volume"))),
            "traffic_share": 0.0,
            "organic_page": op,
            "organic_pos": opos,
            "ad_page": ap,
            "ad_pos": apos,
        })
    if not terms:
        raise MCPError("Sorftime 返回 0 条关键词")
    estimate_shares(terms)
    return {"source": "sorftime", "estimated_share": True, "tool": "product_traffic_terms", "terms": terms}


def estimate_shares(terms: List[Dict[str, Any]]) -> None:
    """Fill traffic_share from search volume x position weight (in-place)."""
    for term in terms:
        w = _weight(term.get("organic_page") or 0, term.get("organic_pos") or 0) if term.get("organic_pos") else 0.0
        if term.get("ad_pos"):
            w += _weight(term.get("ad_page") or 0, term.get("ad_pos") or 0, ad=True)
        term["_weight"] = w * (term.get("search_volume") or 1.0)
    total = sum(t.get("_weight") or 0 for t in terms) or 1.0
    for term in terms:
        term["traffic_share"] = (term.get("_weight") or 0) / total
        term.pop("_weight", None)


# --------------------------------------------------------------------------- public
def collect(asin: str, site: str, out_dir: Path, label: str = "", force: str = "", week_end: str = "") -> Dict[str, Any]:
    load_env()
    settings = load_config("settings.json", {}) or {}
    notes: List[str] = []
    result: Optional[Dict[str, Any]] = None
    order = ["sif", "sorftime"] if force != "sorftime" else ["sorftime"]
    if force == "sif":
        order = ["sif"]
    for source in order:
        try:
            if source == "sif":
                result = _from_sif(asin, site, settings, week_end)
            else:
                result = _from_sorftime(asin, site, settings)
            break
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{source}: {exc}")
    if not result:
        raise MCPError(f"{asin} 关键词取数失败；" + " | ".join(notes))

    result.update({"asin": asin, "site": site, "label": label, "captured_at": _today()})
    result["notes"] = notes
    result = shape(result, settings)
    write_json(out_dir / "raw" / f"keywords-{asin}.json", result)
    return result


def _today() -> str:
    import datetime as dt
    return dt.date.today().isoformat()


def shape(data: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sort, cap to top-N and build the 80% traffic cover lists."""
    settings = settings or (load_config("settings.json", {}) or {})
    thresholds = settings.get("thresholds") or {}
    top_n = int(thresholds.get("top_keywords") or 15)
    cover = float(thresholds.get("traffic_cover") or 0.80)

    terms = sorted(data.get("terms") or [], key=lambda t: t.get("traffic_share") or 0, reverse=True)
    cumulative = 0.0
    for term in terms:
        cumulative += term.get("traffic_share") or 0
        term["cum_share"] = cumulative
    covered = [t for t in terms if t["cum_share"] - (t["traffic_share"] or 0) < cover]

    max_rows = int(thresholds.get("max_kw_rows") or 60)
    organic = [t for t in terms if t.get("organic_pos")][:max_rows]
    ads = [t for t in terms if t.get("ad_pos") or t.get("ad_label")][:max_rows]
    data["terms"] = terms
    data["organic"] = organic
    data["ads"] = ads
    data["top80"] = covered
    data["coverage"] = covered[-1]["cum_share"] if covered else 0.0
    data["cover_count"] = len(covered)
    data["total_terms"] = len(terms)
    data["coverage_label"] = pct(min(cumulative, 1.0), 0)
    return data


def load_snapshot(out_dir: Path, asin: str) -> Optional[Dict[str, Any]]:
    return read_json(out_dir / "raw" / f"keywords-{asin}.json", None)
