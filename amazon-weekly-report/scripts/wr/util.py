"""Shared helpers: env loading, JSON IO, number/date formatting, week math."""
from __future__ import annotations

import calendar
import datetime as dt
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
EXAMPLES_DIR = ROOT / "examples"


# --------------------------------------------------------------------------- env
def load_env(path: Optional[Path] = None) -> None:
    """Minimal .env loader; never overwrites real environment variables."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


# --------------------------------------------------------------------------- io
def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config(name: str, default: Any = None) -> Any:
    return read_json(CONFIG_DIR / name, default)


# --------------------------------------------------------------------------- week
def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value)[:10].replace("/", "-"))


def week_monday(value: Optional[str] = None) -> dt.date:
    """Return the Monday of the week containing value (default: last complete week)."""
    if value and value not in ("current", "last"):
        day = parse_date(value)
        return day - dt.timedelta(days=day.weekday())
    today = dt.date.today()
    this_monday = today - dt.timedelta(days=today.weekday())
    if value == "current":
        return this_monday
    return this_monday - dt.timedelta(days=7)


def week_days(monday: dt.date) -> List[dt.date]:
    return [monday + dt.timedelta(days=i) for i in range(7)]


def iso_week_label(monday: dt.date) -> str:
    year, week, _ = monday.isocalendar()
    return f"{year} 年第 {week} 周"


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# --------------------------------------------------------------------------- nums
def num(value: Any, default: float = 0.0) -> float:
    """Parse a number that may arrive as '1,234', '$12.30', '12.3%', '-', None."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value) if not (isinstance(value, float) and math.isnan(value)) else default
    text = str(value).strip().replace(",", "").replace("$", "").replace("￥", "")
    if text in ("", "-", "--", "N/A", "n/a", "null", "None", "无"):
        return default
    pct = text.endswith("%")
    text = text.rstrip("%")
    try:
        result = float(text)
    except ValueError:
        return default
    return result / 100 if pct else result


def money(value: Any, currency: str = "USD") -> str:
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥"}
    symbol = symbols.get(currency, "")
    amount = num(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000:
        return f"{sign}{symbol}{amount/1_000_000:,.2f}M"
    return f"{sign}{symbol}{amount:,.0f}" if amount >= 100 else f"{sign}{symbol}{amount:,.2f}"


def pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{num(value) * 100:.{digits}f}%"


def pp(value: Any, digits: int = 1) -> str:
    v = num(value) * 100
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{digits}f}pp"


def integer(value: Any) -> str:
    return f"{num(value):,.0f}"


def signed(value: float, digits: int = 1, suffix: str = "%") -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}{suffix}"


def safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    a, b = num(a), num(b)
    return a / b if b else default


def round_half(value: float, digits: int = 2) -> float:
    return float(f"{num(value):.{digits}f}")


# --------------------------------------------------------------------------- text
def asin_from_url(url: str) -> str:
    text = (url or "").upper()
    for pattern in (r"/DP/([A-Z0-9]{10})", r"/GP/PRODUCT/([A-Z0-9]{10})", r"ASIN[=/]([A-Z0-9]{10})"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    match = re.search(r"\b([A-Z0-9]{10})\b", text)
    return match.group(1) if match else ""


def first(row: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    """Case/space-insensitive lookup across alias keys."""
    if not isinstance(row, dict):
        return default
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for key in keys:
        k = key.strip().lower().replace(" ", "_")
        if k in lowered and lowered[k] not in (None, ""):
            return lowered[k]
    return default


def compact(text: Any, limit: int = 60) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"
