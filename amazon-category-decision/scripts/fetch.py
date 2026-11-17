"""Fetch one Amazon category from Sorftime (or a mapped MCP provider)."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from mcp_client import MCPError
from providers import get_provider


def payload_data(obj: Any) -> Any:
    if isinstance(obj, dict) and "data" in obj:
        return obj["data"]
    return obj


def save(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def search(provider_name: str, category: str, site: str) -> List[Dict[str, Any]]:
    provider = get_provider(provider_name)
    raw = provider.call("category_search", {"category_name": category, "amz_site": site})
    data = payload_data(raw)
    if isinstance(data, list):
        return data
    return []


def fetch(
    provider_name: str,
    slug: str,
    site: str,
    category: str = "",
    node: str = "",
    outroot: Path = Path("data"),
    pulled: str = "",
) -> Path:
    provider = get_provider(provider_name)
    pulled = pulled or date.today().isoformat()
    if not node:
        candidates = search(provider_name, category, site)
        if not candidates:
            raise MCPError(f"No category candidates for {category!r}")
        if len(candidates) > 1:
            print("Multiple candidates; pass --node explicitly:")
            for c in candidates:
                print(f"  {c.get('node_id')}  {c.get('category_name')}")
            raise MCPError("Ambiguous category; use --node")
        node = str(candidates[0]["node_id"])
        category = candidates[0].get("category_name") or category

    raw_dir = outroot / slug / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    def call(key: str, args: Dict[str, Any]) -> Any:
        return payload_data(provider.call(key, args))

    print(f"[1/6] category report node={node}")
    report = call("category_report", {"node_id": str(node), "amz_site": site})
    save(raw_dir / "category_report.json", report)

    print("[2/6] Top100 products")
    products = call("category_products", {"node_id": str(node), "amz_site": site})
    save(raw_dir / "products.json", products)

    print("[3/6] category keywords")
    keywords: List[Dict[str, Any]] = []
    for page in (1, 2):
        part = call("category_keywords", {"node_id": str(node), "amz_site": site, "page": page})
        if isinstance(part, list):
            keywords.extend(part)
        time.sleep(0.2)
    save(raw_dir / "keywords.json", keywords)

    print("[4/6] category trends")
    trends: Dict[str, Any] = {}
    for idx in ["SalesCount", "AvgPrice", "AmazonSalesAmountShare", "NewProductSalesAmountShare", "Top3ProductSalesAmountShare"]:
        trends[idx] = call("category_trend", {"node_id": str(node), "amz_site": site, "trend_index": idx})
        time.sleep(0.2)
    save(raw_dir / "trends.json", trends)

    print("[5/6] keyword detail + trend (top 4)")
    keyword_details: Dict[str, Any] = {}
    keyword_trends: Dict[str, Any] = {}
    def relevance(term: str) -> int:
        tokens = [t.rstrip("s") for t in re.split(r"[^a-z0-9]+", category.lower()) if len(t) > 2]
        return sum(1 for t in tokens if t and t in term.lower())

    top_terms = sorted(
        keywords,
        key=lambda k: (relevance(k.get("keyword") or ""), int(float(k.get("monthly_search_volume") or 0))),
        reverse=True,
    )[:4]
    for k in top_terms:
        term = k.get("keyword") or ""
        if not term:
            continue
        try:
            keyword_details[term] = call("keyword_detail", {"keyword": term, "keyword_support_site": site})
        except MCPError as exc:
            print(f"  ! keyword_detail {term}: {exc}")
        try:
            keyword_trends[term] = call("keyword_trend", {"keyword": term, "type": 2, "keyword_support_site": site})
        except MCPError as exc:
            print(f"  ! keyword_trend {term}: {exc}")
        time.sleep(0.25)
    save(raw_dir / "keyword_details.json", keyword_details)
    save(raw_dir / "keyword_trends.json", keyword_trends)

    print("[6/6] top product details + review summaries")
    top = sorted(products or [], key=lambda p: int(p.get("monthly_sales_volume") or 0), reverse=True)[:10]
    details: Dict[str, Any] = {}
    for p in top:
        asin = p.get("asin")
        if not asin:
            continue
        try:
            details[asin] = call("product_detail", {"asin": asin, "amz_site": site})
        except MCPError as exc:
            print(f"  ! product_detail {asin}: {exc}")
        time.sleep(0.2)
    save(raw_dir / "product_details.json", details)

    says: Dict[str, Any] = {}
    contents: Dict[str, Any] = {}
    for p in top[:3]:
        asin = p.get("asin")
        if not asin:
            continue
        try:
            says[asin] = call("product_customers_say", {"asin": asin, "site": site})
        except MCPError as exc:
            print(f"  ! customers_say {asin}: {exc}")
        try:
            contents[asin] = call("product_content", {"asin": asin, "amz_site": site})
        except MCPError as exc:
            print(f"  ! product_content {asin}: {exc}")
        time.sleep(0.2)
    save(raw_dir / "customers_say.json", says)
    save(raw_dir / "product_content.json", contents)

    save(raw_dir / "meta.json", {"provider": provider_name, "site": site, "node": str(node), "category": category, "slug": slug, "pulled": pulled})
    print(f"RAW OK {raw_dir}")
    return raw_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="sorftime", choices=["sorftime", "sif"])
    parser.add_argument("--slug", required=True)
    parser.add_argument("--site", default="US")
    parser.add_argument("--category", default="")
    parser.add_argument("--node", default="")
    parser.add_argument("--out", default="data")
    parser.add_argument("--pulled", default="")
    args = parser.parse_args()
    fetch(args.provider, args.slug, args.site, args.category, args.node, Path(args.out), args.pulled)


if __name__ == "__main__":
    main()
