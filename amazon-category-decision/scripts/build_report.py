"""Render a standalone HTML report from data.json + narrative.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "report.html"
STYLE = ROOT / "templates" / "style.css"

REQUIRED_NARRATIVE = [
    "hero", "kpis", "scores", "gates", "overview", "demand",
    "competition", "products", "concepts", "data",
]


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check(data: Dict[str, Any], narrative: Dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_NARRATIVE if k not in narrative]
    if missing:
        raise ValueError("narrative.json missing keys: " + ", ".join(missing))
    if not narrative.get("gates"):
        raise ValueError("narrative.gates is empty")
    if not narrative.get("kpis"):
        raise ValueError("narrative.kpis is empty")
    if not data.get("products"):
        raise ValueError("data.products is empty")
    if not data.get("market", {}).get("months"):
        raise ValueError("data.market.months is empty")


def build(slug: str, root: Path = Path("data"), out: str = "") -> Path:
    data_path = root / slug / "data.json"
    narrative_path = root / slug / "narrative.json"
    if not data_path.exists():
        raise FileNotFoundError(data_path)
    if not narrative_path.exists():
        raise FileNotFoundError(narrative_path)
    data = load(data_path)
    narrative = load(narrative_path)
    check(data, narrative)

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__STYLE__", STYLE.read_text(encoding="utf-8"))
    html = html.replace("__TITLE__", f"{data.get('meta', {}).get('category', slug)} · 类目分析")
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace("__NARRATIVE__", json.dumps(narrative, ensure_ascii=False).replace("</", "<\\/"))
    out_path = Path(out) if out else (root / slug / "report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--root", default="data")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    print(build(args.slug, Path(args.root), args.out))


if __name__ == "__main__":
    main()
