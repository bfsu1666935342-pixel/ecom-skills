#!/usr/bin/env python3
"""Listing 写作：校验 + Excel 导出。

流程：员工把草稿写成 draft-<spu>.json → 本脚本校验 → 通过才出 Excel。

草稿结构：
{
  "spu": "LS-66D38",
  "product": "办公椅",
  "title": "…",
  "bullets": [
    {"text": "…", "keyword": "big and tall gaming chair", "scene": "居家久坐"},
    …
  ],
  "backend": "…",
  "style_refs": ["k-xxxx"],          // 必须来自知识库（分类 Listing，含风格/语气/句式）
  "audience": [{"id": "a1", "text": "居家办公久坐族"}],
  "scenes": [{"id": "s1", "text": "宠物抢座"}]
}

用法：
  python listing.py build --input draft.json [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

BANNED = [
    "best seller", "best-selling", "cheapest", "100%", "guaranteed cure",
    "#1 ", "number one", "fda", "medical grade", "cure", "treat ",
]
BAD_OPENERS = ["this chair", "our product", "this product", "the chair is"]
SCENE_HINTS = [
    "i ", "my ", "we ", "after ", "before ", "when ", "weekend", "morning",
    "evening", "night", "office", "home", "dorm", "desk", "kids", "child",
    "dog", "cat", "hours", "month", "week", "summer", "winter",
]
STYLE_HINTS = ["风格", "语气", "句式", "人称", "句长", "语气词", "口吻"]


def data_dir() -> Path:
    for cand in [
        os.environ.get("ECOM_DATA", ""),
        str(SKILL.parent.parent / "ecom-workbench" / "data"),
        str(Path.cwd() / "data"),
    ]:
        if cand and (Path(cand) / "knowledge.json").exists():
            return Path(cand)
    return SKILL.parent.parent / "ecom-workbench" / "data"


def load_knowledge() -> dict:
    p = data_dir() / "knowledge.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return {it["id"]: it for it in doc.get("items", []) if not it.get("deleted")}
    except Exception:
        return {}


def words(text: str) -> list:
    return re.findall(r"[a-z']+", str(text or "").lower())


def check(draft: dict, kb: dict) -> list:
    """返回违规项列表，空列表=通过"""
    bad = []
    title = str(draft.get("title") or "").strip()
    bullets = [b for b in (draft.get("bullets") or []) if isinstance(b, dict)]
    backend = str(draft.get("backend") or "").strip()

    # 标题
    if not title:
        bad.append("标题为空")
    else:
        if len(title) > 200:
            bad.append(f"标题 {len(title)} 字符，超过 200")
        head = title[:80].lower()
        kws = [str(b.get("keyword") or "").lower() for b in bullets if b.get("keyword")]
        if kws and not any(k in head for k in kws):
            bad.append("标题前 80 字符没有出现任何埋入词")

    # 五点
    if len(bullets) < 5:
        bad.append(f"五点只有 {len(bullets)} 条，至少 5 条")
    confirmed_scenes = {str(s.get("text") or "") for s in (draft.get("scenes") or [])}
    for i, b in enumerate(bullets, 1):
        text = str(b.get("text") or "").strip()
        if not text:
            bad.append(f"五点第 {i} 条为空")
            continue
        if len(text) > 500:
            bad.append(f"五点第 {i} 条 {len(text)} 字符，超过 500")
        if text.lower().startswith(tuple(BAD_OPENERS)):
            bad.append(f"五点第 {i} 条以第三人称套话开头")
        kw = str(b.get("keyword") or "").strip()
        if kw and kw.lower() not in text.lower():
            bad.append(f"五点第 {i} 条没埋入分配的词「{kw}」")
        hits = sum(1 for h in SCENE_HINTS if h in text.lower())
        if hits < 2:
            bad.append(f"五点第 {i} 条缺具体场景（人/时间/动作）")
        scene = str(b.get("scene") or "")
        if confirmed_scenes and scene and scene not in confirmed_scenes:
            bad.append(f"五点第 {i} 条用了未确认的场景「{scene}」")

    # 后台词
    if backend:
        if len(backend.encode("utf-8")) > 250:
            bad.append(f"后台词 {len(backend.encode('utf-8'))} 字节，超过 250")
        ws = words(backend)
        dup = {w for w in ws if ws.count(w) > 1}
        if dup:
            bad.append("后台词有重复：" + "、".join(sorted(dup)[:5]))

    # 禁词 / 竞品
    whole = (title + " " + " ".join(str(b.get("text") or "") for b in bullets)).lower()
    for w in BANNED:
        if w in whole:
            bad.append(f"出现禁词「{w.strip()}」")
    for brand in draft.get("competitor_brands") or []:
        if brand and str(brand).lower() in whole:
            bad.append(f"出现竞品品牌「{brand}」")

    # 关键词密度
    tw = words(whole)
    if tw:
        kws = [str(b.get("keyword") or "").lower() for b in bullets if b.get("keyword")]
        hit = sum(1 for k in kws for _ in re.finditer(re.escape(k), whole))
        if hit / max(1, len(tw)) > 0.05:
            bad.append(f"关键词密度 {hit/len(tw)*100:.1f}%，超过 5%（像堆砌）")

    # 知识库引用（风格必须来自库）
    refs = draft.get("style_refs") or []
    if not refs:
        bad.append("缺 style_refs：先 search_knowledge 取风格条目再写")
    else:
        for rid in refs:
            item = kb.get(str(rid))
            if not item:
                bad.append(f"style_refs 里的「{rid}」在知识库中不存在")
                continue
            if "Listing" not in str(item.get("category") or ""):
                bad.append(f"「{rid}」不是 Listing 分类，不能当写作风格")
            if not any(h in str(item.get("content") or "") for h in STYLE_HINTS):
                bad.append(f"「{rid}」看起来不是风格规则（没提到语气/句式/人称）")

    return bad


def export(draft: dict, out: Path, violations: list) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Listing"
    head_fill = PatternFill("solid", fgColor="1F2937")
    thin = Side(style="thin", color="D9DDE3")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = ["#", "模块", "英文内容（直接复制）", "字符数", "埋入词", "场景", "备注"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border
    ws.row_dimensions[1].height = 24

    rows = [["1", "Title", draft.get("title", ""), len(str(draft.get("title", ""))), "", "", ""]]
    for i, b in enumerate(draft.get("bullets") or [], 1):
        text = str(b.get("text") or "")
        rows.append([str(i + 1), f"Bullet {i}", text, len(text), str(b.get("keyword") or ""), str(b.get("scene") or ""), ""])
    if draft.get("backend"):
        rows.append([str(len(rows) + 1), "Search Terms", draft["backend"], len(draft["backend"]), "", "", "不含已埋词，≤250 字节"])

    for r, row in enumerate(rows, 2):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = border
            cell.alignment = Alignment(vertical="top", horizontal="center" if c in (1, 4) else "left", wrap_text=c == 3)
        ws.row_dimensions[r].height = max(30, min(120, 15 * (len(str(row[2])) // 60 + 1)))

    for c, w in {1: 4, 2: 12, 3: 78, 4: 8, 5: 22, 6: 14, 7: 20}.items():
        ws.column_dimensions[chr(64 + c)].width = w
    ws.freeze_panes = "A2"

    if violations:
        bad = wb.create_sheet("未通过项")
        bad["A1"] = "以下问题未通过校验"
        bad["A1"].font = Font(bold=True)
        for i, v in enumerate(violations, 3):
            bad.cell(row=i, column=1, value=str(i - 2))
            bad.cell(row=i, column=2, value=v)
        bad.column_dimensions["B"].width = 80

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("cmd", nargs="?", default="build")
    parser.add_argument("--input", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--force", action="store_true")
    args, _ = parser.parse_known_args()

    src = Path(args.input) if args.input else Path.cwd() / "draft-listing.json"
    if not src.exists():
        print(f"找不到草稿：{src}")
        return 2

    draft = json.loads(src.read_text(encoding="utf-8"))
    kb = load_knowledge()
    violations = check(draft, kb)

    spu = draft.get("spu") or "listing"
    out = Path(args.out) if args.out else src.parent / f"listing-{spu}.xlsx"

    if violations and not args.force:
        print(f"未通过校验，共 {len(violations)} 项（没生成正式文件）：")
        for v in violations:
            print("  ✗ " + v)
        print("\n改完草稿再跑一次。确实要生成（带未通过页）加 --force。")
        return 1

    export(draft, out, violations)
    if violations:
        print(f"已生成（带 {len(violations)} 项未通过）：{out}")
    else:
        print(f"已生成：{out}")
    print(f"标题 {len(str(draft.get('title') or ''))} 字符，五点 {len(draft.get('bullets') or [])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
