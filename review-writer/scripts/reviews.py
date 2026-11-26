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
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

def _candidates():
    """技能运行时 cwd 是技能目录，工作区在别处，所以往上层找 workspace/。"""
    out = [os.environ.get("REVIEW_INPUT", ""), str(Path.cwd() / "review-input.json")]
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


def build(xlsx):
    from openpyxl import Workbook  # 延迟导入，doctor 不需要
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

    head_fill = PatternFill("solid", fgColor="F2F4F7")
    thin = Side(style="thin", color="DDE1E6")
    border = Border(bottom=thin)
    bold = Font(bold=True)

    headers = ["#", "语言", "星级", "长度", "夸奖点", "人设", "场景", "使用时长", "评论正文"]
    for col, name in enumerate(headers, start=1):
        cell = en.cell(row=1, column=col, value=name)
        cell.font = bold
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for i, item in enumerate(reviews, start=1):
        row = i + 1
        values = [
            i,
            doc.get("language") or "en",
            item.get("stars") or 5,
            doc.get("length") or "",
            "、".join(item.get("points") or []),
            item.get("persona") or "",
            item.get("scene") or "",
            item.get("used") or "",
            item.get("text") or "",
        ]
        for col, value in enumerate(values, start=1):
            cell = en.cell(row=row, column=col, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 9))
            cell.border = border

    zh_headers = ["#", "中文对照", "夸奖点"]
    for col, name in enumerate(zh_headers, start=1):
        cell = zh.cell(row=1, column=col, value=name)
        cell.font = bold
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for i, item in enumerate(reviews, start=1):
        row = i + 1
        for col, value in enumerate(
            [i, item.get("text_zh") or item.get("text") or "", "、".join(item.get("points") or [])], start=1
        ):
            cell = zh.cell(row=row, column=col, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 2))
            cell.border = border

    widths = {1: 5, 2: 7, 3: 6, 4: 8, 5: 24, 6: 28, 7: 34, 8: 12, 9: 80}
    for col, w in widths.items():
        en.column_dimensions[get_column_letter(col)].width = w
    for col, w in {1: 5, 2: 80, 3: 24}.items():
        zh.column_dimensions[get_column_letter(col)].width = w
    en.freeze_panes = "A2"
    zh.freeze_panes = "A2"

    src = find_input(args.input)
    name = f"reviews-{dt.datetime.now():%Y%m%d-%H%M}.xlsx"
    if xlsx:
        out = Path(xlsx)
    else:
        # 主产出放技能自己的 reports/，工作台会把它复制到「技能产出」
        out = SKILL / "reports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    # 再放一份到输入文件旁边（工作区根目录），方便直接打开
    try:
        if src.parent.resolve() != out.parent.resolve():
            import shutil

            shutil.copyfile(out, src.parent / out.name)
            print(f"副本：{src.parent / out.name}")
    except OSError:
        pass
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
