"""Deterministic checks for a generated category report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

WEIGHTS = {"demand": .30, "competition": .25, "economics": .25, "differentiation": .10, "supply": .05, "content": .05}


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_total(narrative: Dict[str, Any]) -> int:
    scores = narrative.get("scores") or {}
    return round(sum(float(scores.get(k, 0)) * w for k, w in WEIGHTS.items()))


def verify(slug: str, root: Path = Path("data")) -> List[str]:
    errors: List[str] = []
    data_path = root / slug / "data.json"
    narrative_path = root / slug / "narrative.json"
    report_path = root / slug / "report.html"
    for p in (data_path, narrative_path, report_path):
        if not p.exists():
            errors.append(f"missing {p}")
    if errors:
        return errors

    data = load(data_path)
    narrative = load(narrative_path)
    html = report_path.read_text(encoding="utf-8")

    if not data.get("products"):
        errors.append("data.products empty")
    if not data.get("market", {}).get("months"):
        errors.append("data.market.months empty")
    if len(data.get("market", {}).get("months", [])) != len(data.get("market", {}).get("sales", [])):
        errors.append("market months/sales length mismatch")
    if len(data.get("products", [])) < 5:
        errors.append("fewer than 5 products in table")
    if not data.get("keywords"):
        errors.append("data.keywords empty")

    for key in ("hero", "kpis", "scores", "gates", "overview", "demand", "competition", "products", "concepts", "data"):
        if key not in narrative:
            errors.append(f"narrative missing {key}")
    for gate in narrative.get("gates", []):
        if gate.get("status") not in ("pass", "warn", "fail", "unknown"):
            errors.append(f"bad gate status: {gate}")
    for kpi in narrative.get("kpis", []):
        if not kpi.get("label") or kpi.get("value") in (None, ""):
            errors.append(f"bad kpi: {kpi}")

    score = narrative.get("total_score")
    if score is None:
        errors.append("narrative.total_score missing")
    elif not (0 <= float(score) <= 100):
        errors.append(f"score out of range: {score}")
    else:
        calc = expected_total(narrative)
        if abs(float(score) - calc) > 1:
            errors.append(f"score {score} != weighted {calc} (tolerance 1)")

    for token in ("__DATA__", "__NARRATIVE__", "__STYLE__", "undefined", "NaN"):
        if token in html:
            errors.append(f"render token/undefined present: {token}")

    if len(html) < 20000:
        errors.append(f"report too small: {len(html)} bytes")
    if "http" in html and "amazon.com/dp/" not in html:
        errors.append("external product links missing")
    if data.get("meta", {}).get("source") and "api" in html.lower() and "apikey" not in html.lower():
        # not a hard failure; keeps the check honest without scanning secrets
        pass

    coverage = (narrative.get("data") or {}).get("coverage")
    if not coverage:
        errors.append("narrative.data.coverage missing")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--root", default="data")
    args = parser.parse_args()
    errors = verify(args.slug, Path(args.root))
    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print("PASS: report/data/narrative consistent")


if __name__ == "__main__":
    main()
