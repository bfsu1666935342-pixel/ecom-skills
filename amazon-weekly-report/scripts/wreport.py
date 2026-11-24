"""CLI for the Amazon weekly report skill.

Usage:
  python scripts/wreport.py init --site US --spu 66D50F --parent B0XXXXXXXX --competitor https://...
  python scripts/wreport.py doctor --provider lingxing
  python scripts/wreport.py schema
  python scripts/wreport.py run --product 66D50F
  python scripts/wreport.py demo
  python scripts/wreport.py check --product 66D50F
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wr import collect_keywords, collect_lingxing, competitor, compute, demo, pipeline  # noqa: E402
from wr.util import (  # noqa: E402
    ROOT,
    asin_from_url,
    load_config,
    load_env,
    money,
    num,
    pct,
    read_json,
    safe_div,
    week_monday,
    write_json,
)

DATA_ROOT = ROOT / "data"


# --------------------------------------------------------------------------- helpers
def products() -> dict:
    return load_config("products.json", {"products": []}) or {"products": []}


def find_product(key: str) -> dict:
    items = products().get("products") or []
    for item in items:
        if key and key.lower() in {str(item.get("id", "")).lower(), str(item.get("spu", "")).lower()}:
            return item
    if len(items) == 1:
        return items[0]
    raise SystemExit(f"找不到产品 {key!r}；现有：{[i.get('spu') for i in items]}")


def data_dir_for(product: dict, override: str = "") -> Path:
    if override:
        return Path(override)
    return DATA_ROOT / f"{product.get('site', 'US')}-{product.get('spu', 'SPU')}"


def select_products(key: str) -> list:
    items = [p for p in (products().get("products") or []) if p.get("enabled", True)]
    if key:
        return [find_product(key)]
    if not items:
        raise SystemExit("还没有登记产品，先跑 init")
    return items


def report_dir(selected: list, monday, override: str = "") -> Path:
    if override:
        return Path(override)
    if len(selected) == 1:
        return data_dir_for(selected[0])
    return DATA_ROOT / "weekly" / monday.isoformat()


# --------------------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> int:
    cfg = products()
    items = cfg.get("products") or []
    parents = args.parent or []
    if not parents:
        raise SystemExit("至少给一个父体 ASIN：--parent B0XXXXXXXX")
    comp_asin = args.competitor_asin or asin_from_url(args.competitor or "")
    item = {
        "id": args.spu,
        "spu": args.spu,
        "site": args.site.upper(),
        "title": args.title or f"{args.spu}（{args.site.upper()}）",
        "parents": [{"asin": p.upper(), "label": ""} for p in parents],
        "competitor": {"url": args.competitor or "", "asin": comp_asin, "note": ""},
        "price": args.price,
        "rating": args.rating,
        "enabled": True,
    }
    replaced = False
    for index, existing in enumerate(items):
        if str(existing.get("id")) == args.spu or str(existing.get("spu")) == args.spu:
            items[index] = item
            replaced = True
            break
    if not replaced:
        items.append(item)
    cfg["products"] = items
    write_json(ROOT / "config" / "products.json", cfg)
    print(f"已{'更新' if replaced else '新增'} {args.spu}（{args.site.upper()}），父体 {', '.join(parents)}")
    if comp_asin:
        print(f"竞品 ASIN：{comp_asin}")
    else:
        print("未识别竞品 ASIN，可在 config/products.json 里补 competitor.asin")
    print("下一步：把月目标/成本填进 config/targets.json，然后跑 doctor + run")
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    path = ROOT / "config" / "targets.json"
    targets = read_json(path, {}) or {}
    entry = targets.get(args.spu) or {}
    if args.monthly is not None:
        entry["default_monthly"] = args.monthly
        month = args.month or dt.date.today().strftime("%Y-%m")
        entry.setdefault("monthly", {})[month] = args.monthly
        print(f"  月目标（{month}）：{args.monthly:,.0f}")
    if args.margin is not None:
        entry["target_margin"] = args.margin
    cost = entry.get("cost") or {}
    for key, value in (("unit_cost", args.unit_cost), ("first_leg", args.first_leg), ("fba_fee", args.fba),
                       ("referral_rate", args.referral), ("other_per_unit", args.other)):
        if value is not None:
            cost[key] = value
    if cost:
        entry["cost"] = cost
    if args.note:
        entry["rules_note"] = args.note
    if args.week_override:
        overrides = entry.get("weekly_overrides") or {}
        for item in args.week_override:
            if "=" not in item:
                raise SystemExit(f"--week-override 需要 周一=金额，例如 2026-11-09=120000，收到 {item!r}")
            day, value = item.split("=", 1)
            overrides[day] = float(value)
        entry["weekly_overrides"] = overrides
    targets[args.spu] = entry
    write_json(path, targets)
    print(f"已写入 config/targets.json → {args.spu}")
    print(f"  月目标 {entry.get('default_monthly', '—')} / 目标利润率 {entry.get('target_margin', '—')} / 成本 {entry.get('cost', {})}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = products().get("products") or []
    if not items:
        print("还没有产品，先跑 init")
        return 0
    for item in items:
        parents = " / ".join(p.get("asin", "") for p in item.get("parents") or [])
        comp = (item.get("competitor") or {}).get("asin", "")
        print(f"{item.get('site')}  {item.get('spu')}  父体 {parents}  竞品 {comp or '—'}")
    return 0


# --------------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    load_env()
    provider = args.provider
    try:
        if provider == "lingxing":
            result = collect_lingxing.doctor()
            print(json.dumps({k: v for k, v in result.items() if k != "tools"}, ensure_ascii=False, indent=2))
            if args.list_tools and result.get("tools"):
                print("\n".join(result["tools"]))
            return 0 if result.get("ok") else 1
        if provider == "sif":
            tools = collect_keywords.sif_tools()
            print(f"SIF 已连通，{len(tools)} 个工具")
            if args.list_tools:
                for tool in tools:
                    print(f"- {tool.get('name')}: {(tool.get('description') or '')[:90]}")
            return 0
        if provider == "sorftime":
            from wr.collect_keywords import _sorftime_client
            client = _sorftime_client(load_config("settings.json", {}) or {})
            tools = client.list_tools()
            print(f"Sorftime 已连通，{len(tools)} 个工具")
            if args.list_tools:
                for tool in tools:
                    print(f"- {tool.get('name')}")
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"连接失败：{exc}")
        return 1
    raise SystemExit(f"未知 provider: {provider}")


def cmd_schema(args: argparse.Namespace) -> int:
    try:
        result = collect_lingxing.dump_schemas(ROOT / "config" / "lingxing.schema.json")
    except Exception as exc:  # noqa: BLE001
        print(f"抓取 schema 失败：{exc}")
        return 1
    print(f"已写入 config/lingxing.schema.json，共 {result['tool_count']} 个工具")
    mapped = result.get("mapped") or {}
    for key, name in mapped.items():
        tool = result["tools"].get(name)
        if not tool:
            print(f"  {key}: {name}  ✗ 不在工具列表")
            continue
        props = list(((tool.get("inputSchema") or {}).get("properties") or {}).keys())
        required = (tool.get("inputSchema") or {}).get("required") or []
        print(f"  {key}: {name}  参数 {props}  必填 {required}")
    return 0


# --------------------------------------------------------------------------- collect
def cmd_collect(args: argparse.Namespace) -> int:
    load_env()
    selected = select_products(args.product)
    monday = week_monday(args.week)
    if args.out and len(selected) > 1:
        raise SystemExit("--out 只能用于单个 SPU；多 SPU 默认写到 data/weekly/<周一>/")
    print(f"抓取 {len(selected)} 个 SPU · {monday.isoformat()} 起一周")

    from wr.util import env
    if not args.no_lingxing and not env("LINGXING_MCP_KEY"):
        print("  ! 未配置 LINGXING_MCP_KEY，跳过领星；没有经营数据就无法生成报告。先到工作台「数据源」里配好领星（保存即生效），或在本技能 .env 里填 LINGXING_MCP_KEY。")
        args.no_lingxing = True

    only = [x.strip() for x in (args.only or "").split(",") if x.strip()] or None
    for product in selected:
        out = data_dir_for(product)
        out.mkdir(parents=True, exist_ok=True)
        print(f"- {product.get('spu')} · {product.get('site')} → {out}")

        if not args.no_lingxing:
            lingxing = collect_lingxing.collect(product, monday, out, only=only)
            errors = lingxing.get("errors") or {}
            print(f"  领星：本周 {lingxing.get('this', {}).get('row_count', 0)} 行 / 上周 {lingxing.get('last', {}).get('row_count', 0)} 行")
            for key, message in errors.items():
                print(f"    ! {key}: {message}")
        else:
            print("  跳过领星")

        if not args.no_keywords:
            for parent in product.get("parents") or []:
                asin = parent.get("asin")
                if not asin:
                    continue
                print(f"  关键词 {asin}：抓取中…", flush=True)
                try:
                    kw = collect_keywords.collect(asin, product.get("site", "US"), out, label=parent.get("label", ""), force=args.keyword_source, week_end=(monday + dt.timedelta(days=6)).isoformat())
                    print(f"  关键词 {asin}：{len(kw.get('terms') or [])} 词，来源 {kw.get('source')}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! 关键词 {asin} 失败：{exc}")

        comp_cfg = product.get("competitor") or {}
        comp_asin = comp_cfg.get("asin") or asin_from_url(comp_cfg.get("url", ""))
        if comp_asin and not args.no_competitor:
            print(f"  竞品 {comp_asin}：抓取中…", flush=True)
            try:
                comp = competitor.collect(comp_asin, product.get("site", "US"), out, url=comp_cfg.get("url", ""), force_keyword_source=args.keyword_source, week_end=(monday + dt.timedelta(days=6)).isoformat())
                print(f"  竞品 {comp_asin}：{comp.get('title', '')[:40]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ! 竞品 {comp_asin} 失败：{exc}")

    if args.build:
        target_dir = report_dir(selected, monday, args.out)
        try:
            combined = pipeline.build_report(selected, monday, DATA_ROOT, target_dir)
        except RuntimeError as exc:
            print(f"生成失败：{exc}")
            return 1
        print(f"  报告：{target_dir / 'report.html'}（{len(combined['products'])} 个 SPU）")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    selected = select_products(args.product)
    monday = week_monday(args.week)
    if args.out and len(selected) > 1:
        raise SystemExit("--out 只能用于单个 SPU；多 SPU 默认写到 data/weekly/<周一>/")
    out = report_dir(selected, monday, args.out)
    try:
        combined = pipeline.build_report(selected, monday, DATA_ROOT, out, demo=args.demo)
    except RuntimeError as exc:
        print(f"生成失败：{exc}")
        return 1
    print(f"报告：{out / 'report.html'}（{len(combined['products'])} 个 SPU）")
    for row in combined["overview"]:
        print(f"  {row['spu']} 销售额 {money(row['revenue'])} / 目标 {money(row['target']) if row.get('target') else '—'} / 达成 {pct(row.get('attainment')) if row.get('attainment') is not None else '—'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    args.build = True
    return cmd_collect(args)


# --------------------------------------------------------------------------- demo
def cmd_demo(args: argparse.Namespace) -> int:
    monday = week_monday(args.week or "2026-11-09")
    root = Path(args.out) if args.out else ROOT / "examples" / "weekly-demo"
    bundle = demo.write_multi(root, monday)
    combined = pipeline.build_report(
        bundle["products"], monday, root, root,
        demo=True, targets_override=bundle["targets"],
    )
    print(f"演示报告：{root / 'report.html'}（{len(combined['products'])} 个 SPU）")
    for row in combined["overview"]:
        print(f"  {row['spu']} 销售额 {money(row['revenue'])} / 目标 {money(row['target']) if row.get('target') else '—'} / 达成 {pct(row.get('attainment')) if row.get('attainment') is not None else '—'} / 利润率 {pct(row.get('actual_margin'))}")
    return 0


# --------------------------------------------------------------------------- check
def cmd_check(args: argparse.Namespace) -> int:
    selected = select_products(args.product)
    monday = week_monday(args.week)
    out = report_dir(selected, monday, args.out or "")
    failures = []
    notes = []

    data_path = out / "data.json"
    if not data_path.exists():
        print(f"缺少 {data_path}")
        return 1
    bundle = read_json(data_path)
    datas = bundle.get("products") or [bundle]

    def close(a: float, b: float, tol: float = 0.01) -> bool:
        return abs(a - b) <= max(abs(b) * tol, 1e-6)

    for data in datas:
        overview = data["overview"][0]
        spu = data["spus"][0]
        m = spu["metrics"]
        label = f"{spu['spu']}："
        daily = spu.get("daily") or []
        if daily:
            units = sum(num(d.get("units")) for d in daily)
            revenue = sum(num(d.get("revenue")) for d in daily)
            if not close(units, m["units"]):
                failures.append(f"{label}日销合计 {units} ≠ 周销量 {m['units']}")
            if not close(revenue, m["revenue"]):
                failures.append(f"{label}日销售额合计 {revenue} ≠ 周销售额 {m['revenue']}")
        target = overview.get("target")
        if target and not close(overview["attainment"], safe_div(overview["revenue"], target), 0.001):
            failures.append(f"{label}达成率与 销售额/目标 不一致")
        margin = overview.get("actual_margin")
        if margin is not None and not close(margin, safe_div(overview.get("profit") or 0, overview["revenue"]), 0.001):
            failures.append(f"{label}利润率与 利润/销售额 不一致")
        if data["meta"].get("week_start") != monday.isoformat():
            failures.append(f"{label}报告周 {data['meta'].get('week_start')} 与请求周 {monday.isoformat()} 不一致")
        for parent in spu.get("parents") or []:
            kw = parent.get("keywords") or {}
            terms = kw.get("terms") or []
            if not terms:
                notes.append(f"{parent.get('asin')} 没有关键词数据")
                continue
            top = kw.get("top80") or []
            cover = sum(num(t.get("traffic_share")) for t in top)
            if top and cover < 0.79:
                failures.append(f"{parent.get('asin')} 前 80% 列表累计只有 {pct(cover)}")
        if not spu.get("has_last"):
            notes.append(f"{spu['spu']} 上周数据缺失")
        if data["meta"].get("keywords_estimated"):
            notes.append("关键词占比为估算（Sorftime 无占比字段）")

    total_parents = sum(len((d["spus"][0].get("parents") or [])) for d in datas)
    html_path = out / "report.html"
    if not html_path.exists():
        failures.append("缺少 report.html")
    else:
        html = html_path.read_text(encoding="utf-8")
        if len(html) < 12000:
            failures.append(f"report.html 过小（{len(html)} 字符）")
        for token in ("None", "NaN", "undefined", "__DATA__"):
            if token in html:
                failures.append(f"report.html 含非法占位 {token}")
        for section in ("本周结论", "总览", "整体数据", "广告数据", "关键词结构", "竞品"):
            if section not in html:
                failures.append(f"report.html 缺少段落：{section}")
        if html.count("关键词结构") < total_parents:
            failures.append(f"关键词结构段落 {html.count('关键词结构')} 少于父体数 {total_parents}")
        if html.count("<table") < 6 * len(datas):
            failures.append(f"表格数量偏少（{html.count('<table')}，{len(datas)} 个 SPU）")
        if bundle.get("meta", {}).get("week_start") != monday.isoformat():
            failures.append("报告周与请求周不一致")

    if not (out / "report.md").exists():
        failures.append("缺少 report.md")

    print(f"检查 {out}（{len(datas)} 个 SPU）")
    for note in dict.fromkeys(notes):
        print(f"  - {note}")
    if failures:
        for failure in failures:
            print(f"  [X] {failure}")
        return 1
    print("  [OK] 数字一致、段落齐全、无非法占位")
    return 0


# --------------------------------------------------------------------------- parser
def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(prog="wreport", description="Amazon 周报：领星 + SIF/Sorftime → 飞书文档")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="首次使用：登记站点/SPU/父体/竞品")
    p_init.add_argument("--site", default="US")
    p_init.add_argument("--spu", required=True)
    p_init.add_argument("--parent", action="append", help="父体 ASIN，可重复")
    p_init.add_argument("--competitor", default="", help="竞品链接或 ASIN")
    p_init.add_argument("--competitor-asin", default="")
    p_init.add_argument("--title", default="")
    p_init.add_argument("--price", type=float, default=0)
    p_init.add_argument("--rating", type=float, default=0)
    p_init.set_defaults(func=cmd_init)

    p_list = sub.add_parser("list", help="列出已登记产品")
    p_list.set_defaults(func=cmd_list)

    p_targets = sub.add_parser("targets", help="写入月目标/利润率/成本（来自飞书文档或用户口述）")
    p_targets.add_argument("--spu", required=True)
    p_targets.add_argument("--monthly", type=float, help="月销售额目标（当地币种）")
    p_targets.add_argument("--month", default="", help="目标月份 YYYY-MM，默认本月")
    p_targets.add_argument("--margin", type=float, help="目标利润率，例如 0.16")
    p_targets.add_argument("--unit-cost", type=float, help="单件采购成本")
    p_targets.add_argument("--first-leg", type=float, help="单件头程")
    p_targets.add_argument("--fba", type=float, help="单件 FBA 配送费")
    p_targets.add_argument("--referral", type=float, help="佣金费率，例如 0.15")
    p_targets.add_argument("--other", type=float, help="单件其他成本")
    p_targets.add_argument("--note", default="", help="利润核算规则原文")
    p_targets.add_argument("--week-override", action="append", help="按周一覆盖：2026-11-09=120000，可重复")
    p_targets.set_defaults(func=cmd_targets)

    p_doc = sub.add_parser("doctor", help="检查数据源连通性与工具映射")
    p_doc.add_argument("--provider", choices=["lingxing", "sif", "sorftime"], default="lingxing")
    p_doc.add_argument("--list-tools", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_schema = sub.add_parser("schema", help="导出领星工具参数 schema")
    p_schema.set_defaults(func=cmd_schema)

    for name, func in (("collect", cmd_collect), ("run", cmd_run)):
        p = sub.add_parser(name, help="抓数（run 会顺带生成报告）")
        p.add_argument("--product", default="")
        p.add_argument("--week", default="", help="周内任意一天，默认上周")
        p.add_argument("--out", default="")
        p.add_argument("--only", default="", help="只抓某几项：performance,campaign,keyword,profit")
        p.add_argument("--keyword-source", choices=["", "sif", "sorftime"], default="")
        p.add_argument("--no-lingxing", action="store_true")
        p.add_argument("--no-keywords", action="store_true")
        p.add_argument("--no-competitor", action="store_true")
        p.add_argument("--build", action="store_true")
        p.set_defaults(func=func)

    p_build = sub.add_parser("build", help="用已抓快照生成 data.json + report.html")
    p_build.add_argument("--product", default="")
    p_build.add_argument("--week", default="")
    p_build.add_argument("--out", default="")
    p_build.add_argument("--demo", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_demo = sub.add_parser("demo", help="生成演示周报（不联网）")
    p_demo.add_argument("--week", default="2026-11-09")
    p_demo.add_argument("--out", default="")
    p_demo.set_defaults(func=cmd_demo)

    p_check = sub.add_parser("check", help="校验数字与报告完整性")
    p_check.add_argument("--product", default="")
    p_check.add_argument("--week", default="")
    p_check.add_argument("--out", default="")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
