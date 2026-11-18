"""Build data.json + report.html from raw snapshots (no network)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import collect_keywords, compute
from .render import render_html, render_markdown, render_markdown_report, render_report
from .util import load_config, read_json, write_json


def load_keywords(data_dir: Path, asin: str) -> Dict[str, Any]:
    return read_json(data_dir / "raw" / f"keywords-{asin}.json", {}) or {}


def load_competitor(data_dir: Path, asin: str) -> Optional[Dict[str, Any]]:
    if not asin:
        return None
    return read_json(data_dir / "raw" / f"competitor-{asin}.json", None)


def build_product(
    product: Dict[str, Any],
    week_start: dt.date,
    data_dir: Path,
    *,
    demo: bool = False,
    write_report: bool = True,
    targets_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    lingxing = read_json(data_dir / "raw" / "lingxing.json", {}) or {}
    if not demo and not (lingxing.get("this") or {}).get("row_count"):
        raise RuntimeError(
            f"没有领星本周数据（{data_dir / 'raw' / 'lingxing.json'}）。先跑 collect/run，或确认 --week、SPU、站点。"
        )
    settings = load_config("settings.json", {}) or {}
    keywords = {}
    for parent in product.get("parents") or []:
        asin = parent.get("asin")
        if asin:
            kw = load_keywords(data_dir, asin)
            if kw:
                kw = collect_keywords.shape(kw, settings)
            keywords[asin] = kw
    comp_cfg = product.get("competitor") or {}
    competitor = load_competitor(data_dir, comp_cfg.get("asin", ""))

    targets = targets_override or load_config("targets.json", {}) or {}
    data = compute.build(product, week_start, lingxing, keywords, competitor, targets, settings, demo=demo)

    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "data.json", data)
    if write_report:
        (data_dir / "report.html").write_text(render_html(data, demo=demo), encoding="utf-8")
        (data_dir / "report.md").write_text(render_markdown(data), encoding="utf-8")
    return data


def build_report(
    products: List[Dict[str, Any]],
    week_start: dt.date,
    data_root: Path,
    out_dir: Path,
    *,
    demo: bool = False,
    targets_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    datas: List[Dict[str, Any]] = []
    for product in products:
        product_dir = data_root / f"{product.get('site', 'US')}-{product.get('spu')}"
        datas.append(build_product(
            product, week_start, product_dir,
            demo=demo, write_report=len(products) == 1, targets_override=targets_override,
        ))
    combined = {
        "meta": {
            **datas[0]["meta"],
            "spu_count": len(datas),
            "generated_at": dt.date.today().isoformat(),
        },
        "products": datas,
        "overview": [d["overview"][0] for d in datas],
        "findings": [f for d in datas for f in d.get("findings") or []],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "data.json", combined)
    (out_dir / "report.html").write_text(render_report(datas, demo=demo), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown_report(datas), encoding="utf-8")
    return combined
