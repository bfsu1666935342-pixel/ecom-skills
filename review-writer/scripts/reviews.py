#!/usr/bin/env python3
"""把 review-input.json 渲染成双语 Excel。

输入 JSON 结构（由员工写在工作区 review-input.json）：
{
  "product": "办公椅",
  "language": "en",
  "length": "medium",
  "points": ["坐垫柔软", "靠背高", "面料透气"],
  "reviews": [
    {
      "stars": 5,
      "title": "英文标题…",
      "title_zh": "中文标题…",
      "persona": "带娃的上班族，35 岁，家里养猫",
      "scene": "每天在家办公 8 小时，猫和孩子抢椅子",
      "used": "用了 3 周",
      "points": ["坐垫柔软", "靠背高"],
      "text": "英文正文…",
      "text_zh": "中文对照…"
    }
  ]
}

用法：
  python reviews.py build [--input path] [--out path]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

def _candidates():
    """技能运行时 cwd 是技能目录，工作区在别处，所以往上层找 workspace/。"""
    ws = os.environ.get("ECOM_WORKSPACE", "")
    out = [os.environ.get("REVIEW_INPUT", "")]
    if ws:
        out.append(str(Path(ws) / "review-input.json"))
    out.append(str(Path.cwd() / "review-input.json"))
    here = SKILL
    for _ in range(5):
        out.append(str(here / "review-input.json"))
        out.append(str(here / "workspace" / "review-input.json"))
        try:
            out.extend(str(p) for p in here.glob("*/workspace/review-input.json"))
        except OSError:
            pass
        here = here.parent
        if here == here.parent:
            break
    return [x for x in out if x]


CANDIDATES = _candidates()


def find_input(explicit: str = "") -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise SystemExit(f"找不到输入文件：{explicit}")
    for item in CANDIDATES:
        if item and Path(item).exists():
            return Path(item)
    tried = "\n".join("  " + x for x in CANDIDATES)
    raise SystemExit(
        "找不到 review-input.json。找过这些位置：\n" + tried + "\n把员工写好的 JSON 放到工作区根目录，或用 --input 指定。"
    )


def _title(item):
    """标题字段兼容：title / 标题 / headline"""
    for key in ("title", "标题", "headline"):
        v = (item or {}).get(key)
        if v:
            return str(v)
    return ""

def _points(item):
    """夸奖点兼容：数组、或用、/，/ 分隔的字符串"""
    pts = (item or {}).get("points")
    if isinstance(pts, list):
        return [str(x).strip() for x in pts if str(x).strip()]
    if isinstance(pts, str):
        return [p.strip() for p in re.split(r"[、,，/;；|]", pts) if p.strip()]
    return []


def build(xlsx):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    doc = json.loads(find_input(args.input).read_text(encoding="utf-8"))
    reviews = doc.get("reviews") or []
    if not reviews:
        raise SystemExit("review-input.json 里没有 reviews")

    wb = Workbook()
    en = wb.active
    en.title = "Comments"
    zh = wb.create_sheet("中文对照")

    HEAD_FILL = PatternFill("solid", fgColor="1F2937")
    ZEBRA = PatternFill("solid", fgColor="F7F8FA")
    LINE = Side(style="thin", color="D9DDE3")
    BORDER = Border(left=LINE, right=LINE, top=LINE, bottom=LINE)
    HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
    BODY_FONT = Font(size=10)
    TITLE_FONT = Font(size=10, bold=True)

    headers = ["#", "语言", "星级", "标题", "长度", "夸奖点", "人设", "场景", "使用时长", "评论正文"]
    for col, name in enumerate(headers, start=1):
        cell = en.cell(row=1, column=col, value=name)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER
    en.row_dimensions[1].height = 26

    for i, item in enumerate(reviews, start=1):
        row = i + 1
        values = [
            i,
            doc.get("language") or "en",
            item.get("stars") or 5,
            _title(item),
            doc.get("length") or "",
            " · ".join(_points(item)),
            item.get("persona") or "",
            item.get("scene") or "",
            item.get("used") or "",
            item.get("text") or "",
        ]
        for col, value in enumerate(values, start=1):
            cell = en.cell(row=row, column=col, value=value)
            cell.font = TITLE_FONT if col == 4 else BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(
                vertical="top",
                horizontal="center" if col in (1, 2, 3, 5) else "left",
                wrap_text=col in (4, 6, 7, 8, 10),
            )
            if i % 2 == 0:
                cell.fill = ZEBRA
        text_len = len(str(item.get("text") or ""))
        en.row_dimensions[row].height = max(42, min(210, 15 * (text_len // 75 + 1)))

    widths = {1: 4, 2: 6, 3: 6, 4: 38, 5: 8, 6: 22, 7: 24, 8: 30, 9: 11, 10: 72}
    for col, w in widths.items():
        en.column_dimensions[get_column_letter(col)].width = w
    en.freeze_panes = "A2"
    en.auto_filter.ref = f"A1:J{len(reviews) + 1}"
    en.sheet_properties.tabColor = "1F2937"

    zh_headers = ["#", "标题", "中文对照", "夸奖点"]
    for col, name in enumerate(zh_headers, start=1):
        cell = zh.cell(row=1, column=col, value=name)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER
    zh.row_dimensions[1].height = 26
    for i, item in enumerate(reviews, start=1):
        row = i + 1
        values = [
            i,
            item.get("title_zh") or _title(item),
            item.get("text_zh") or item.get("text") or "",
            " · ".join(_points(item)),
        ]
        for col, value in enumerate(values, start=1):
            cell = zh.cell(row=row, column=col, value=value)
            cell.font = TITLE_FONT if col == 2 else BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(
                vertical="top", horizontal="center" if col in (1, 4) else "left", wrap_text=col in (2, 3)
            )
            if i % 2 == 0:
                cell.fill = ZEBRA
        zh.row_dimensions[row].height = max(42, min(180, 15 * (len(str(item.get("text_zh") or "")) // 60 + 1)))

    for col, w in {1: 4, 2: 34, 3: 68, 4: 22}.items():
        zh.column_dimensions[get_column_letter(col)].width = w
    zh.freeze_panes = "A2"
    zh.sheet_properties.tabColor = "6B7280"

    src_path = find_input(args.input)
    name = f"reviews-{dt.datetime.now():%Y%m%d-%H%M}.xlsx"
    out = Path(xlsx) if xlsx else SKILL / "reports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    try:
        if src_path.parent.resolve() != out.parent.resolve():
            import shutil

            shutil.copyfile(out, src_path.parent / out.name)
            print(f"副本：{src_path.parent / out.name}")
    except OSError:
        pass
    missing = [str(i + 1) for i, r in enumerate(reviews) if not _title(r)]
    if missing:
        print(f"警告：第 {', '.join(missing)} 条缺标题")
    print(f"已生成：{out}")
    print(f"条数：{len(reviews)}｜语言：{doc.get('language') or 'en'}｜长度：{doc.get('length') or '-'}")
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sub = sys.argv[1] if len(sys.argv) > 1 else "build"
    if sub not in ("build",):
        print("用法：python reviews.py build [--input review-input.json] [--out reviews.xlsx]")
        return 2
    build(args.out)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", default="")
    parser.add_argument("--out", default="")
    args, _unknown = parser.parse_known_args()
    raise SystemExit(main())
