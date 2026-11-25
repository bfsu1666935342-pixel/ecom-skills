"""Render data.json into a Feishu-friendly HTML page and a Markdown fallback.

The HTML is deliberately plain: headings, paragraphs and tables only. CSS is for
on-screen reading; tables also carry inline styles so that a copy-paste into a
Feishu doc keeps borders, header shading and column alignment.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .util import money, num, pct, pp, safe_div

CSS = """
:root{--ink:#1f2329;--muted:#646a73;--line:#e5e6eb;--soft:#f7f8fa;--accent:#1f4ed8;--warn:#c2410c}
*{box-sizing:border-box}
body{margin:0;background:#eef0f3;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif;font-size:15px;line-height:1.7;-webkit-font-smoothing:antialiased}
.page{max-width:860px;margin:0 auto;background:#fff;padding:56px 60px 64px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.doc-head{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:34px}
.eyebrow{font-size:12px;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin-bottom:10px}
h1{font-size:30px;line-height:1.35;margin:0 0 12px;font-weight:700;letter-spacing:-.01em}
.meta{font-size:13px;color:var(--muted);line-height:1.9}
.meta span{margin-right:14px;white-space:nowrap}
h2{font-size:21px;margin:46px 0 16px;padding-left:12px;border-left:4px solid var(--ink);line-height:1.4}
h3{font-size:16px;margin:30px 0 10px;font-weight:600}
h4{font-size:14px;margin:20px 0 8px;color:var(--muted);font-weight:600}
p{margin:10px 0}
.note{font-size:12.5px;color:var(--muted);line-height:1.75;margin:8px 0 0}
.findings{background:var(--soft);border-left:3px solid var(--ink);padding:18px 22px;margin:0 0 8px}
.findings ul{margin:0;padding-left:18px}
.findings li{margin:7px 0}
.findings b{font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:10px 0 6px;font-variant-numeric:tabular-nums}
th{background:var(--soft);font-weight:600;text-align:left;border-bottom:1px solid #cfd3d9;padding:8px 10px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:7px 10px;vertical-align:top}
tr:last-child td{border-bottom:1px solid #cfd3d9}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.center{text-align:center}
.tag{display:inline-block;font-size:11.5px;padding:0 6px;border:1px solid currentColor;border-radius:2px;margin-right:8px;line-height:1.6;vertical-align:1px}
.high{color:#b42318}.warn{color:var(--warn)}.good{color:#067647}.info{color:var(--muted)}
.spark{font-family:Consolas,Menlo,monospace;letter-spacing:1px;font-size:15px;color:var(--accent)}
.rule{height:1px;background:var(--line);margin:34px 0}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:1.8}
.copybar{position:fixed;right:24px;top:20px;z-index:9}
.copybar button{font:inherit;font-size:13px;padding:8px 14px;border:1px solid #cfd3d9;background:#fff;border-radius:4px;cursor:pointer;color:var(--ink)}
.copybar button:hover{border-color:var(--ink)}
.toast{position:fixed;right:24px;top:64px;background:#1f2329;color:#fff;font-size:13px;padding:8px 12px;border-radius:4px;opacity:0;transition:opacity .2s;z-index:10}
.toast.show{opacity:1}
.hero-target{display:flex;gap:36px;margin:18px 0 6px}
.kpi{flex:1;border-top:2px solid var(--ink);padding-top:8px}
.kpi .v{font-size:24px;font-weight:700;line-height:1.3}
.kpi .l{font-size:12px;color:var(--muted)}
@media print{body{background:#fff}.page{box-shadow:none;padding:0}.copybar{display:none}}
"""

COPY_JS = """
(function(){
  var btn=document.getElementById('copyBtn');
  var toast=document.getElementById('toast');
  function show(t){toast.textContent=t;toast.classList.add('show');setTimeout(function(){toast.classList.remove('show')},1800)}
  btn.addEventListener('click',async function(){
    var doc=document.getElementById('doc');
    try{
      var html='<meta charset="utf-8">'+doc.innerHTML;
      await navigator.clipboard.write([new ClipboardItem({
        'text/html':new Blob([html],{type:'text/html'}),
        'text/plain':new Blob([doc.innerText],{type:'text/plain'})
      })]);
      show('已复制，去飞书文档里粘贴');
    }catch(e){
      var range=document.createRange();range.selectNodeContents(doc);
      var sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);
      try{document.execCommand('copy');show('已复制，去飞书文档里粘贴')}catch(err){show('复制失败，请手动全选复制')}
    }
  });
})();
"""

TABLE = "border-collapse:collapse;width:100%;font-size:13.5px;"
TH = "background:#f7f8fa;font-weight:600;text-align:left;border-bottom:1px solid #cfd3d9;padding:8px 10px;"
TD = "border-bottom:1px solid #e5e6eb;padding:7px 10px;vertical-align:top;"


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def fmt_value(value: Any, kind: str, currency: str = "USD") -> str:
    if value is None:
        return "—"
    if kind == "money":
        return money(value, currency)
    if kind == "money2":
        return f"${num(value):,.2f}"
    if kind == "num":
        return f"{num(value):,.1f}" if abs(num(value)) < 100 else f"{num(value):,.0f}"
    if kind == "int":
        return f"{num(value):,.0f}"
    if kind == "pct":
        return pct(value, 1)
    if kind == "pct2":
        return pct(value, 2)
    return str(value)


def _delta_html(item: Optional[Dict[str, Any]], kind: str) -> str:
    if not item:
        return "—"
    label = item.get("label") or "—"
    diff = item.get("abs") or 0
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "·")
    return f"{arrow} {esc(label)}"


def _table(headers: List[str], rows: List[List[str]], align: Optional[List[str]] = None) -> str:
    align = align or ["left"] * len(headers)

    def style_for(kind: str) -> str:
        extra = "text-align:right;white-space:nowrap;" if kind == "right" else ("text-align:center;" if kind == "center" else "")
        return extra

    head = "".join(f'<th style="{TH}{style_for(align[i])}">{esc(h)}</th>' for i, h in enumerate(headers))
    body = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            cls = ' class="num"' if align[i] == "right" else (' class="center"' if align[i] == "center" else "")
            cells.append(f'<td style="{TD}{style_for(align[i])}"{cls}>{cell}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table style="{TABLE}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _spark(values: List[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return blocks[3] * len(values)
    out = []
    for value in values:
        idx = int(round((value - low) / (high - low) * (len(blocks) - 1)))
        out.append(blocks[idx])
    return "".join(out)


def _pos(page: int, pos: int) -> str:
    if not pos:
        return "—"
    page = page or 1
    if page == 1:
        return f"第1页 {pos}位"
    return f"第{page}页 {pos}位"


def _share(value: Any) -> str:
    v = num(value)
    if 0 < v < 0.001:
        return "<0.1%"
    return pct(v, 1)


def _kw_table(items: List[Dict[str, Any]], mode: str, estimated: bool, currency: str = "USD") -> str:
    if not items:
        return '<p class="note">本期无可用数据。</p>'
    if mode == "organic":
        rows = [[esc(t.get("keyword")), esc(_pos(t.get("organic_page"), t.get("organic_pos"))), _share(t.get("traffic_share")), f"{num(t.get('search_volume')):,.0f}"] for t in items]
        return _table(["关键词", "自然位", "流量占比" + ("（估）" if estimated else ""), "月搜索量"], rows, ["left", "left", "right", "right"])
    if mode == "ads":
        rows = [[esc(t.get("keyword")), esc(t.get("ad_label") or _pos(t.get("ad_page"), t.get("ad_pos"))), esc(_pos(t.get("organic_page"), t.get("organic_pos"))), f"{num(t.get('search_volume')):,.0f}"] for t in items]
        return _table(["关键词", "广告位", "自然位", "月搜索量"], rows, ["left", "left", "left", "right"])
    rows = [[esc(t.get("keyword")), _share(t.get("traffic_share")), _share(t.get("cum_share")), f"{num(t.get('search_volume')):,.0f}"] for t in items]
    return _table(["关键词", "流量占比" + ("（估）" if estimated else ""), "累计", "月搜索量"], rows, ["left", "right", "right", "right"])


def _flag_label(level: str) -> str:
    return {"high": "重点", "warn": "关注", "good": "正常", "info": "提示"}.get(level, "提示")


def _single_page(data: Dict[str, Any], *, demo: bool = False) -> str:
    meta = data["meta"]
    currency = meta.get("currency", "USD")
    spu = data["spus"][0]
    metrics = spu["metrics"]
    wow = metrics.get("wow") or {}
    overview = data["overview"][0]
    comp = data.get("competitor") or {}
    parents = spu.get("parents") or []
    kw_source = meta.get("keywords_source") or "—"
    kw_name = {"sif": "SIF", "sorftime": "Sorftime"}.get(kw_source, kw_source)
    kw_label = kw_name + ("（流量占比为估算）" if meta.get("keywords_estimated") else "")

    parts: List[str] = []
    parts.append('<div class="copybar"><button id="copyBtn" type="button">复制到飞书</button></div><div class="toast" id="toast"></div>')
    parts.append('<div class="page" id="doc">')

    # ---------------------------------------------------------------- header
    title = f"{spu['spu']} · {meta['site_label']} 周报"
    parts.append('<div class="doc-head">')
    parts.append('<div class="eyebrow">AMAZON WEEKLY · 运营周报</div>')
    parts.append(f"<h1>{esc(title)}</h1>")
    meta_bits = [
        f"{meta['week_label']}（{meta['iso_week']}）",
        f"SPU {esc(meta['spu'])}",
        f"父体 {(' / '.join(p['asin'] for p in parents)) or '—'}",
        f"数据源 领星 / {esc(kw_label)}",
    ]
    parts.append('<div class="meta">' + "　·　".join(meta_bits) + "</div>")
    if demo or meta.get("demo"):
        parts.append('<p class="note" style="color:#b42318">演示数据：仅用于确认版式与口径，不是真实经营数据。</p>')
    parts.append("</div>")

    # ---------------------------------------------------------------- findings
    parts.append("<h2>本周结论</h2>")
    parts.append('<div class="findings"><ul>')
    for line in data.get("findings") or []:
        if "｜" in line:
            area, text = line.split("｜", 1)
            parts.append(f"<li><b>{esc(area)}</b>　{esc(text)}</li>")
        else:
            parts.append(f"<li>{esc(line)}</li>")
    parts.append("</ul></div>")

    # ---------------------------------------------------------------- overview
    parts.append("<h2>一、总览</h2>")
    rows = [[
        esc(overview["spu"]),
        f"{num(overview['units']):,.0f}",
        money(overview["revenue"], currency),
        money(overview["target"], currency) if overview.get("target") else "—",
        pct(overview["attainment"]) if overview.get("attainment") is not None else "—",
        (f"{pct(overview.get('target_margin'))} → {pct(overview.get('actual_margin'))}" if overview.get("actual_margin") is not None else "—"),
    ]]
    parts.append(_table(["SPU", "实际销量", "实际销售额", "周目标", "达成率", "利润率（目标 → 实际）"], rows, ["left", "right", "right", "right", "right", "right"]))
    if overview.get("monthly_target") and overview.get("target"):
        parts.append(f'<p class="note">月目标 {money(overview["monthly_target"], currency)}，按当月自然日拆到本周 7 天，周目标 {money(overview["target"], currency)}。同一 SPU 下多个链接已合并。</p>')
    else:
        parts.append('<p class="note">销量与销售额取领星 SPU 维度；同一 SPU 下多个链接已合并。</p>')

    # ---------------------------------------------------------------- per SPU
    parts.append(f"<h2>二、{esc(spu['spu'])} 分项</h2>")
    if len(parents) > 1:
        parts.append(f'<p class="note">该 SPU 下有 {len(parents)} 个父体：{esc(" / ".join(p["asin"] for p in parents))}。广告与关键词均按父体分别展开；活动明细为 SPU 合并（活动可能跨父体投放，无法归属到单一父体）。</p>')

    # A
    parts.append("<h3>A　整体数据（领星）</h3>")
    metric_rows = []
    kinds = {
        "units_per_day": "num", "aov": "money", "sessions_per_day": "num", "clicks_per_day": "num",
        "ctr": "pct2", "ad_cvr": "pct2", "cvr": "pct2", "cpc": "money2",
        "acoas": "pct2", "ad_order_share": "pct", "return_rate": "pct2", "refund_rate": "pct2",
    }
    labels = {
        "units_per_day": "日销（件）", "aov": "客单价", "sessions_per_day": "日均总会话",
        "clicks_per_day": "日均点击", "ctr": "日均 CTR", "ad_cvr": "广告 CVR",
        "cvr": "整体 CVR", "cpc": "CPC", "acoas": "ACoAS", "ad_order_share": "广告订单占比",
        "return_rate": "退货率", "refund_rate": "退款率",
    }
    for key, label in labels.items():
        cur = fmt_value(metrics.get(key), kinds[key], currency)
        last_metrics = spu.get("last") or {}
        prev = fmt_value(last_metrics.get(key), kinds[key], currency) if spu.get("has_last") else "—"
        metric_rows.append([esc(label), cur, prev, _delta_html(wow.get(key), kinds[key])])
    parts.append(_table(["指标", "本周", "上周", "变化"], metric_rows, ["left", "right", "right", "right"]))
    parts.append('<p class="note">点击、CTR、曝光取领星广告口径（广告点击 ÷ 广告曝光）；整体 CVR = 订单 ÷ 会话；ACoAS = 广告花费 ÷ 总销售额。' + ("" if spu.get("has_last") else "上周数据缺失，变化列不做对比。") + "</p>")

    daily = spu.get("daily") or []
    if daily:
        units = [num(d.get("units")) for d in daily]
        parts.append(f'<p class="note">近 {len(units)} 天日销趋势：<span class="spark">{_spark(units)}</span>　最低 {min(units):,.0f} / 最高 {max(units):,.0f}</p>')

    profit = spu.get("profit") or {}
    gap = (profit.get("rate") or 0) - (profit.get("target_rate") or 0)
    show_breakdown = bool(profit.get("breakdown")) and (not profit.get("target_rate") or gap <= -0.02)
    if show_breakdown:
        parts.append("<h4>利润核算</h4>")
        revenue = num(profit["breakdown"].get("销售额")) or 1
        rows = []
        for name, value in profit["breakdown"].items():
            rows.append([esc(name), money(value, currency), pct(safe_div(value, revenue), 1)])
        rows.append(["利润", money(profit.get("amount"), currency), pct(profit.get("rate"), 1)])
        parts.append(_table(["项目", "金额", "占销售额"], rows, ["left", "right", "right"]))
        parts.append(f'<p class="note">{esc(profit.get("note") or "")} 目标利润率 {pct(profit.get("target_rate"))}，实际 {pct(profit.get("rate"))}。</p>')
    elif profit.get("breakdown"):
        parts.append(f'<p class="note">利润 {money(profit.get("amount"), currency)}，利润率 {pct(profit.get("rate"))}（目标 {pct(profit.get("target_rate"))}）；成本明细见 data.json。</p>')
    elif profit.get("source") == "lingxing":
        parts.append(f'<p class="note">利润取自领星：{money(profit.get("amount"), currency)}，利润率 {pct(profit.get("rate"))}（目标 {pct(profit.get("target_rate"))}）。</p>')

    # B
    ads = spu.get("ads") or {}
    summary = ads.get("summary") or {}
    parts.append("<h3>B　广告数据（领星）</h3>")
    last_ads = spu.get("last") or {}
    ad_rows = [
        ("曝光", "ad_impressions", "int"),
        ("点击", "ad_clicks", "int"),
        ("点击率", "ad_ctr", "pct2"),
        ("CPC", "cpc", "money2"),
        ("广告 CVR", "ad_cvr", "pct2"),
        ("广告订单", "ad_orders", "int"),
        ("广告销量", "ad_units", "int"),
        ("广告销售额", "ad_sales", "money"),
        ("广告花费", "ad_spend", "money"),
        ("ACOS", "acos", "pct"),
        ("CPA", "cpa", "money2"),
    ]
    rows = []
    for label, key, kind in ad_rows:
        cur = fmt_value(metrics.get(key), kind, currency)
        prev = fmt_value(last_ads.get(key), kind, currency) if spu.get("has_last") else "—"
        rows.append([esc(label), cur, prev, _delta_html(wow.get(key), kind)])
    parts.append(_table(["指标", "本周", "上周", "变化"], rows, ["left", "right", "right", "right"]))
    units_note = "广告销量缺失时按广告订单数代替。" if (summary or {}).get("units_fallback") else ""
    parts.append('<p class="note">本表为 SPU 合计（含 SP/SD/SB）；各父体拆分见下表。CPC = 花费 ÷ 点击，CPA = 花费 ÷ 广告订单。' + units_note + "</p>")

    parent_list = spu.get("parents") or []
    multi = len(parent_list) > 1
    parent_ads = [p for p in parent_list if (p.get("ads") or {}).get("available")]
    if len(parent_list) > 1 and parent_ads:
        parts.append("<h4>按父体拆分的广告</h4>")
        rows = []
        for p in parent_ads:
            a = p.get("ads") or {}
            rows.append([
                esc(p.get("asin") or ""),
                pct(a.get("spend_share"), 1),
                money(a.get("ad_spend"), currency),
                money(a.get("ad_sales"), currency),
                pct(a.get("acos"), 2),
                f"{num(a.get('ad_orders')):,.0f}",
                f"{num(a.get('ad_clicks')):,.0f}",
                f"{num(a.get('ad_units') or a.get('ad_orders')):,.0f}",
            ])
        parts.append(
            _table(
                ["父体 ASIN", "花费占比", "广告花费", "广告销售额", "ACOS", "广告订单", "广告点击", "广告销量"],
                rows,
                ["left", "right", "right", "right", "right", "right", "right", "right"],
            )
        )
        missing = [p.get("asin") for p in parent_list if not (p.get("ads") or {}).get("available")]
        extra = ""
        if missing:
            extra = " 以下父体无 ASIN 维度数据：" + "、".join(str(x) for x in missing) + "。"
        parts.append(
            '<p class="note">按父体拆分来自领星「产品表现」的 ASIN 维度行（含 SP/SD/SB）；'
            "同一父体下多个子体的广告已合并到该父体。活动与关键词按「活动×商品」归属到父体，跨父体投放的标为「跨父体」，取不到商品明细的标为「未归属」。"
            + extra
            + (" 广告销量缺失时按广告订单代替。" if any((p.get("ads") or {}).get("ad_units_fallback") for p in parent_ads) else "")
            + "</p>"
        )

    if daily:
        rows = []
        for day in daily:
            rows.append([
                esc(str(day.get("date"))[5:]),
                f"{num(day.get('ad_impressions')):,.0f}",
                f"{num(day.get('ad_clicks')):,.0f}",
                pct(day.get("ad_ctr"), 2),
                f"${num(day.get('cpc')):,.2f}",
                pct(day.get("ad_cvr"), 2),
                f"{num(day.get('ad_units')):,.0f}",
                pct(day.get("acos"), 2),
                pct(day.get("acoas"), 2),
            ])
        parts.append("<h4>每日广告表现</h4>")
        parts.append(
            _table(
                ["日期", "曝光", "点击", "CTR", "CPC", "CVR", "广告销量", "ACOS", "ACoAS"],
                rows,
                ["left", "right", "right", "right", "right", "right", "right", "right", "right"],
            )
        )

    if multi and parent_ads:
        rows = []
        for p in parent_ads:
            for day in ((p.get("ads") or {}).get("daily") or []):
                rows.append([
                    esc(str(day.get("date"))[5:]),
                    esc(p.get("asin") or ""),
                    f"{num(day.get('ad_impressions')):,.0f}",
                    f"{num(day.get('ad_clicks')):,.0f}",
                    pct(day.get("ad_ctr"), 2),
                    f"${num(day.get('cpc')):,.2f}",
                    pct(day.get("ad_cvr"), 2),
                    f"{num(day.get('ad_units') or day.get('ad_orders')):,.0f}",
                    pct(day.get("acos"), 2),
                    pct(day.get("acoas"), 2),
                ])
        if rows:
            parts.append("<h4>每日广告表现（按父体）</h4>")
            parts.append(
                _table(
                    ["日期", "父体 ASIN", "曝光", "点击", "CTR", "CPC", "CVR", "广告销量", "ACOS", "ACoAS"],
                    rows,
                    ["left", "left", "right", "right", "right", "right", "right", "right", "right", "right"],
                )
            )

    campaigns = ads.get("campaigns") or []
    parts.append("<h4>广告活动</h4>")
    if campaigns:
        rows = []
        for c in campaigns:
            used = c.get("budget_used")
            row = [esc(c.get("name"))]
            heads = ["广告活动"]
            aligns = ["left"]
            if multi:
                row.append(esc(c.get("parents") or "未归属"))
                heads.append("父体")
                aligns.append("left")
            row += [
                money(c.get("budget"), currency) if c.get("budget") else "—",
                money(c.get("spend"), currency),
                pct(used, 0) if used is not None else "—",
                pct(c.get("cvr"), 2),
                f"${num(c.get('cpa')):,.2f}" if c.get("cpa") else "—",
            ]
            rows.append(row)
        heads += ["预算", "花费", "预算使用", "CVR", "CPA"]
        aligns += ["right", "right", "right", "right", "right"]
        parts.append(_table(heads, rows, aligns))
        parts.append('<p class="note">预算使用 = 周花费 ÷ 周预算（日预算已 ×7）；活动按名称包含该 SPU 汇总；跨 SPU 共用活动为活动全量花费，与 B① 的 SPU 广告花费可能有差额。</p>')
    else:
        parts.append('<p class="note">本期无广告活动数据。</p>')

    words = ads.get("keywords") or []
    parts.append("<h4>关键词花费（跨活动）</h4>")
    if words:
        if multi:
            rows = [[esc(w.get("keyword")), esc(w.get("parents") or "未归属"), f"{num(w.get('clicks')):,.0f}", money(w.get("spend"), currency), pct(w.get("spend_share"), 1), pct(w.get("cvr"), 1)] for w in words]
            parts.append(_table(["关键词", "父体", "点击", "花费", "花费占比", "CVR"], rows, ["left", "left", "right", "right", "right", "right"]))
        else:
            rows = [[esc(w.get("keyword")), f"{num(w.get('clicks')):,.0f}", money(w.get("spend"), currency), pct(w.get("spend_share"), 1), pct(w.get("cvr"), 1)] for w in words]
            parts.append(_table(["关键词", "点击", "花费", "花费占比", "CVR"], rows, ["left", "right", "right", "right", "right"]))
        parts.append('<p class="note">按 SPU 汇总所有广告活动下的关键词；同名关键词已合并。</p>')
    else:
        parts.append('<p class="note">本期无关键词花费数据。</p>')

    # C per parent
    for parent in parents:
        kw = parent.get("keywords") or {}
        estimated = bool(kw.get("estimated_share"))
        src = {"sif": "SIF", "sorftime": "Sorftime"}.get(kw.get("source") or "", kw.get("source") or "—")
        heading = f"C　关键词结构 · {parent['asin']}（数据源 {src}"
        if estimated:
            heading += "，流量占比为估算"
        heading += "）"
        parts.append(f"<h3>{esc(heading)}</h3>")
        parts.append("<h4>① 自然位</h4>")
        parts.append(_kw_table(kw.get("organic") or [], "organic", estimated, currency))
        parts.append("<h4>② 广告位</h4>")
        parts.append(_kw_table(kw.get("ads") or [], "ads", estimated, currency))
        parts.append("<h4>③ 流量前 80%</h4>")
        parts.append(_kw_table(kw.get("top80") or [], "top80", estimated, currency))
        if kw.get("total_terms"):
            parts.append(f'<p class="note">本次抓取 {int(kw["total_terms"])} 个有位置的关键词，前 {int(kw.get("cover_count") or 0)} 个贡献约 80% 流量；①② 按流量各展示前 {len(kw.get("organic") or [])} 个，完整列表见 raw 文件。</p>')
        if estimated:
            parts.append('<p class="note">Sorftime 不提供流量占比：占比 = 月搜索量 × 位置权重，在本次抓取到的词内归一化，仅用于排序与结构判断，不等于真实流量份额。</p>')

    # D competitor
    parts.append("<h2>三、竞品</h2>")
    if comp and comp.get("asin"):
        parts.append(f"<h3>{esc(comp.get('asin'))}{(' · ' + esc(comp.get('brand'))) if comp.get('brand') else ''}</h3>")
        basic_rows = [
            ["划线价", f"${num(comp.get('list_price')):,.2f}" if comp.get("list_price") else "—", ""],
            ["现价", f"${num(comp.get('price')):,.2f}" if comp.get("price") else "—", _price_delta(comp)],
            ["折扣", _discount(comp), ""],
            ["活动", ("有券/促销" + (f"（{comp.get('coupon_label')}）" if comp.get("coupon_label") else "")) if comp.get("deal") else "无", ""],
            ["评分", f"{num(comp.get('rating')):.1f}" if comp.get("rating") else "—", _num_delta(comp.get("rating_delta"), 1)],
            ["评论数", f"{num(comp.get('reviews')):,.0f}" if comp.get("reviews") else "—", _num_delta(comp.get("reviews_delta"), 0)],
            ["变体数", f"{num(comp.get('variation_count')):,.0f}" if comp.get("variation_count") else "—", _variation_delta(comp)],
            ["月销（估）", f"{num(comp.get('monthly_sales')):,.0f}" if comp.get("monthly_sales") else "—", ""],
        ]
        parts.append(_table(["指标", "数值", "变化"], basic_rows, ["left", "left", "left"]))
        if comp.get("compared_to"):
            parts.append(f'<p class="note">变化对比 {esc(comp.get("compared_to"))} 的上次快照；首次采集时显示“首次”。</p>')
        else:
            parts.append('<p class="note">首次采集，价格/评分/变体变化从下次运行开始显示。</p>')

        ckw = comp.get("keywords") or {}
        if ckw.get("terms"):
            est = bool(ckw.get("estimated_share"))
            parts.append("<h4>竞品流量结构（前 80%）</h4>")
            parts.append("<h4>① 自然位</h4>")
            parts.append(_kw_table(ckw.get("organic80") or [], "organic", est, currency))
            parts.append("<h4>② 广告位</h4>")
            parts.append(_kw_table(ckw.get("ads80") or [], "ads", est, currency))
            parts.append("<h4>③ 流量前 80%</h4>")
            parts.append(_kw_table(ckw.get("top80") or [], "top80", est, currency))
        else:
            parts.append('<p class="note">竞品关键词暂无数据。</p>')
    else:
        parts.append('<p class="note">未配置竞品链接。</p>')

    # footer
    parts.append('<div class="foot">')
    parts.append(f"数据源：领星 ERP（销量、广告、利润）；{esc(kw_name)}（关键词与位置{('，占比为估算' if meta.get('keywords_estimated') else '')}）。<br>")
    parts.append("口径：周为自然周（周一至周日）；销售额为商品销售额，未扣退款；利润口径见各 SPU 说明。<br>")
    parts.append(f"生成时间 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · amazon-weekly-report")
    parts.append("</div>")
    parts.append("</div>")

    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(meta['week_label'])}</title>
<style>{CSS}</style></head>
<body>
{body}
<script>{COPY_JS}</script>
</body></html>"""


def render_html(data: Dict[str, Any], *, demo: bool = False) -> str:
    """Single-SPU convenience wrapper."""
    return render_report([data], demo=demo)


def _combined_findings(datas: List[Dict[str, Any]]) -> List[str]:
    n = len(datas)
    known = [d for d in datas if d["overview"][0].get("attainment") is not None]
    hit = sum(1 for d in known if (d["overview"][0].get("attainment") or 0) >= 0.95)
    low = sum(1 for d in known if (d["overview"][0].get("attainment") or 0) < 0.85)
    margin_known = [d for d in datas if d["overview"][0].get("target_margin") is not None and d["overview"][0].get("actual_margin") is not None]
    margin_ok = sum(1 for d in margin_known if (d["overview"][0].get("actual_margin") or 0) >= (d["overview"][0].get("target_margin") or 0))
    revenue = sum(num(d["overview"][0].get("revenue")) for d in datas)
    target = sum(num(d["overview"][0].get("target")) for d in datas)
    total = f"合计销售额 {money(revenue)} / 周目标 {money(target)}（{pct(safe_div(revenue, target))}）" if target else f"合计销售额 {money(revenue)}"
    worst = min(known, key=lambda d: d["overview"][0].get("attainment") or 9) if known else None
    worst_att = worst["overview"][0].get("attainment") if worst else None
    focus = f"优先处理 {worst['spus'][0]['spu']}。" if worst_att is not None and worst_att < 0.85 else ""
    if known:
        lead = f"本周 {n} 个 SPU，{total}；{hit} 个达成周目标，{low} 个缺口超过 15%，{margin_ok} 个利润率达到目标。{focus}"
    else:
        lead = f"本周 {n} 个 SPU，{total}；销售目标未配置，达成率暂不计算。"
    lines = [lead]
    priority = {"销售": 0, "利润": 1, "广告": 2, "流量": 3, "转化": 4, "售后": 5, "关键词": 6, "竞品": 7}
    for data in datas:
        spu = data["spus"][0]
        o = data["overview"][0]
        ranked = []
        for finding in data.get("findings") or []:
            area, text = finding.split("｜", 1) if "｜" in finding else ("", finding)
            if area == "数据" or text.startswith("缺周销售目标") or text.startswith("本次抓取") or text.startswith("抓取到的"):
                continue
            ranked.append((priority.get(area, 9), text.rstrip("。")))
        pieces = [text for _, text in sorted(ranked, key=lambda x: x[0])[:2]]
        if not pieces:
            margin = pct(o.get("actual_margin")) if o.get("actual_margin") is not None else "—"
            target_note = "目标缺失" if o.get("target_margin") is None else f"目标 {pct(o.get('target_margin'))}"
            pieces.append(f"销售额 {money(o.get('revenue'))}，销量 {num(o.get('units')):,.0f}，利润率 {margin}（{target_note}）")
        lines.append(f"{spu['spu']}｜" + "；".join(pieces))
    return lines


def _status_tag(data: Dict[str, Any]) -> str:
    o = data["overview"][0]
    att = o.get("attainment")
    if att is None:
        return ""
    if att >= 1:
        label = "达成"
    elif att >= 0.95:
        label = "接近"
    elif att >= 0.85:
        label = "关注"
    else:
        label = "滞后"
    margin, target_margin = o.get("actual_margin"), o.get("target_margin")
    if margin is not None and target_margin and margin - target_margin <= -0.02:
        label += " · 利润承压"
    color = "#b42318" if att < 0.95 else "#1a7f37"
    return f'　<span style="color:{color};font-weight:600">（{label}）</span>'


def _body_of(data: Dict[str, Any], index: int) -> str:
    page = _single_page(data)
    start = page.index("<h2>二、")
    end = page.index('<div class="foot">')
    body = page[start:end]
    body = re.sub(r"<(/?)h([2-4])>", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}>", body)
    spu, meta = data["spus"][0], data["meta"]
    heading = f"<h3>{index}. {esc(spu['spu'])} · {esc(meta['site_label'])}{_status_tag(data)}</h3>"
    body = re.sub(r"<h3>二、.*?</h3>", heading, body, count=1)
    body = body.replace("<h3>三、竞品</h3>", "<h4>D　竞品（对标）</h4>")
    body = re.sub(r"<h4>([A-Z0-9]{10}(?: · .*?)?)</h4>", r"<p><b>\1</b></p>", body, count=1)
    return body


def render_report(datas: List[Dict[str, Any]], *, demo: bool = False) -> str:
    if not datas:
        raise ValueError("没有可渲染的 SPU 数据")
    first = datas[0]["meta"]
    currency = first.get("currency", "USD")
    sites = {d["meta"].get("site_label") or d["meta"].get("site") for d in datas}
    multi_site = len(sites) > 1
    site_label = "多站点" if multi_site else sites.pop()
    parents_total = sum(len(d["spus"][0].get("parents") or []) for d in datas)
    kw_sources = {d["meta"].get("keywords_source") for d in datas if d["meta"].get("keywords_source")}
    kw_name = {"sif": "SIF", "sorftime": "Sorftime"}.get(next(iter(kw_sources), ""), "—")
    estimated = any(d["meta"].get("keywords_estimated") for d in datas)

    title = f"{site_label} · {first['iso_week']}经营周报"
    parts: List[str] = []
    parts.append('<div class="copybar"><button id="copyBtn" type="button">复制到飞书</button></div><div class="toast" id="toast"></div>')
    parts.append('<div class="page" id="doc">')
    parts.append('<div class="doc-head">')
    parts.append('<div class="eyebrow">AMAZON WEEKLY · 运营周报</div>')
    parts.append(f"<h1>{esc(title)}</h1>")
    meta_bits = [
        f"{first['week_label']}（{first['iso_week']}）",
        f"SPU {len(datas)} 个",
        f"父体 {parents_total} 个",
        f"数据源 领星 / {kw_name}" + ("（占比估算）" if estimated else ""),
    ]
    parts.append('<div class="meta">' + "　·　".join(esc(b) for b in meta_bits) + "</div>")
    if demo or first.get("demo"):
        parts.append('<p class="note" style="color:#b42318">演示数据：仅用于确认版式与口径，不是真实经营数据。</p>')
    parts.append("</div>")

    parts.append("<h2>本周结论</h2>")
    parts.append('<div class="findings"><ul>')
    for line in _combined_findings(datas):
        if "｜" in line:
            label, text = line.split("｜", 1)
            parts.append(f"<li><b>{esc(label)}</b>　{esc(text)}</li>")
        else:
            parts.append(f"<li>{esc(line)}</li>")
    parts.append("</ul></div>")

    parts.append("<h2>一、总览</h2>")
    rows = []
    total_units = total_revenue = total_target = total_profit = 0.0
    for data in datas:
        o = data["overview"][0]
        row = [esc(o["spu"])]
        if multi_site:
            row.append(esc(data["meta"].get("site_label") or data["meta"].get("site")))
        row += [
            f"{num(o['units']):,.0f}",
            money(o["revenue"], currency),
            money(o["target"], currency) if o.get("target") else "—",
            pct(o["attainment"]) if o.get("attainment") is not None else "—",
            pct(o.get("target_margin")) if o.get("target_margin") is not None else "—",
            pct(o.get("actual_margin")) if o.get("actual_margin") is not None else "—",
        ]
        rows.append(row)
        total_units += num(o["units"])
        total_revenue += num(o["revenue"])
        total_target += num(o.get("target"))
        total_profit += num(o.get("profit"))
    if len(datas) > 1:
        total_attain = safe_div(total_revenue, total_target) if total_target else None
        total_margin = safe_div(total_profit, total_revenue) if total_revenue else None
        row = [f"<b>合计</b>"]
        if multi_site:
            row.append("")
        row += [
            f"<b>{total_units:,.0f}</b>",
            f"<b>{money(total_revenue, currency)}</b>",
            f"<b>{money(total_target, currency)}</b>" if total_target else "<b>—</b>",
            f"<b>{pct(total_attain)}</b>" if total_attain is not None else "<b>—</b>",
            "—",
            f"<b>{pct(total_margin)}</b>" if total_margin is not None else "<b>—</b>",
        ]
        rows.append(row)
    headers = ["SPU"] + (["站点"] if multi_site else []) + ["实际销量", "实际销售额", "周目标", "达成率", "目标利润率", "实际利润率"]
    aligns = ["left"] + (["left"] if multi_site else []) + ["right"] * 6
    parts.append(_table(headers, rows, aligns))
    first_month = datas[0]["overview"][0]
    if first_month.get("monthly_target"):
        parts.append('<p class="note">周目标 = 月目标 ÷ 当月天数 × 7，跨月按天累加，四舍五入到百位；合计行为各 SPU 相加。</p>')
    else:
        parts.append('<p class="note">销量与销售额取领星 SPU 维度；同一 SPU 下多个链接已合并。</p>')

    parts.append("<h2>二、分 SPU 分析</h2>")
    for index, data in enumerate(datas, start=1):
        parts.append(_body_of(data, index))

    parts.append('<div class="foot">')
    parts.append(f"数据源：领星 ERP（销量、广告、利润）；{esc(kw_name)}（关键词与位置{('，占比为估算' if estimated else '')}）。<br>")
    parts.append("口径：周为自然周（周一至周日）；销售额为商品销售额，未扣退款；利润口径见各 SPU 说明。<br>")
    parts.append(f"生成时间 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · amazon-weekly-report")
    parts.append("</div></div>")

    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(first['week_label'])}</title>
<style>{CSS}</style></head>
<body>
{body}
<script>{COPY_JS}</script>
</body></html>"""


def _price_delta(comp: Dict[str, Any]) -> str:
    delta = comp.get("price_delta")
    if delta is None:
        return "首次"
    if not delta:
        return "持平"
    return f"{'↑' if delta > 0 else '↓'} ${abs(delta):,.2f}"


def _discount(comp: Dict[str, Any]) -> str:
    price, list_price = num(comp.get("price")), num(comp.get("list_price"))
    if not price or not list_price or list_price <= price:
        return "—"
    return f"-{(1 - price / list_price) * 100:.0f}%"


def _num_delta(delta: Any, digits: int) -> str:
    if delta is None:
        return "首次"
    if not delta:
        return "持平"
    return f"{'+' if delta > 0 else ''}{num(delta):,.{digits}f}"


def _variation_delta(comp: Dict[str, Any]) -> str:
    delta = comp.get("variation_delta")
    if delta is None:
        return "首次"
    if not delta:
        return "无变动"
    return f"{'增加' if delta > 0 else '减少'} {abs(int(delta))} 个"


def _md_table(headers: List[str], rows: List[List[str]], right: Optional[List[int]] = None) -> str:
    right = right or []
    aligns = ["---:" if i in right else "---" for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(aligns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def _md_kw(items: List[Dict[str, Any]], mode: str, estimated: bool) -> str:
    if not items:
        return "_本期无可用数据。_\n"
    suffix = "（估）" if estimated else ""
    if mode == "organic":
        return _md_table(["关键词", "自然位", f"流量占比{suffix}", "月搜索量"],
                         [[t.get("keyword"), _pos(t.get("organic_page"), t.get("organic_pos")), _share(t.get("traffic_share")), f"{num(t.get('search_volume')):,.0f}"] for t in items], [2, 3]) + "\n"
    if mode == "ads":
        return _md_table(["关键词", "广告位", "自然位", "月搜索量"],
                         [[t.get("keyword"), _pos(t.get("ad_page"), t.get("ad_pos")), _pos(t.get("organic_page"), t.get("organic_pos")), f"{num(t.get('search_volume')):,.0f}"] for t in items], [3]) + "\n"
    return _md_table(["关键词", f"流量占比{suffix}", "累计", "月搜索量"],
                     [[t.get("keyword"), _share(t.get("traffic_share")), _share(t.get("cum_share")), f"{num(t.get('search_volume')):,.0f}"] for t in items], [1, 2, 3]) + "\n"


def render_markdown(data: Dict[str, Any]) -> str:
    meta, spu = data["meta"], data["spus"][0]
    m = spu["metrics"]
    wow = m.get("wow") or {}
    currency = meta.get("currency", "USD")
    lines = [f"# {spu['spu']} · {meta['site_label']} 周报", "",
             f"{meta['week_label']}（{meta['iso_week']}） · SPU {meta['spu']} · 数据源 领星 / {meta.get('keywords_source', '')}", ""]
    if meta.get("demo"):
        lines += ["> 演示数据：仅用于确认版式与口径，不是真实经营数据。", ""]
    lines += ["## 本周结论", ""]
    for finding in data.get("findings") or []:
        lines.append(f"- {finding}")
    lines.append("")

    o = data["overview"][0]
    lines += ["## 一、总览", "",
              _md_table(["SPU", "实际销量", "实际销售额", "周目标", "达成率", "利润率（目标 → 实际）"],
                        [[o["spu"], f"{num(o['units']):,.0f}", money(o["revenue"], currency),
                          money(o["target"], currency) if o.get("target") else "—",
                          pct(o["attainment"]) if o.get("attainment") is not None else "—",
                          f"{pct(o.get('target_margin'))} → {pct(o.get('actual_margin'))}"]], [1, 2, 3, 4, 5]), "",
              "销量与销售额取领星 SPU 维度；同一 SPU 下多个链接已合并。", ""]

    lines += [f"## 二、{spu['spu']} 分项", "", "### A 整体数据（领星）", ""]
    rows = []
    for key, label in (("units_per_day", "日销（件）"), ("aov", "客单价"), ("sessions_per_day", "日均总会话"),
                       ("clicks_per_day", "日均点击"), ("ctr", "日均 CTR"), ("ad_cvr", "广告 CVR"),
                       ("cvr", "整体 CVR"), ("cpc", "CPC"), ("acoas", "ACoAS"), ("ad_order_share", "广告订单占比"),
                       ("return_rate", "退货率"), ("refund_rate", "退款率")):
        kind = ("pct2" if key in ("ctr", "ad_cvr", "cvr", "acoas", "return_rate", "refund_rate")
                else "pct" if key == "ad_order_share" else "money" if key == "aov" else "money2" if key == "cpc" else "num")
        rows.append([label, fmt_value(m.get(key), kind, currency),
                     fmt_value(spu.get("last", {}).get(key), kind, currency) if spu.get("has_last") else "—",
                     (wow.get(key) or {}).get("label", "—")])
    lines += [_md_table(["指标", "本周", "上周", "变化"], rows, [1, 2, 3]), "",
              "ACoAS = 广告花费 ÷ 总销售额；CTR = 点击 ÷ 曝光；整体 CVR = 订单 ÷ 会话。", ""]

    profit = spu.get("profit") or {}
    if profit.get("breakdown"):
        lines += ["**利润核算**", ""]
        revenue = num(profit["breakdown"].get("销售额")) or 1
        rows = [[name, money(value, currency), pct(safe_div(value, revenue), 1)] for name, value in profit["breakdown"].items()]
        rows.append(["利润", money(profit.get("amount"), currency), pct(profit.get("rate"), 1)])
        lines += [_md_table(["项目", "金额", "占销售额"], rows, [1, 2]), ""]

    lines += ["### B 广告数据（领星）", ""]
    rows = []
    for label, key, kind in (("曝光", "ad_impressions", "int"), ("点击", "ad_clicks", "int"), ("点击率", "ad_ctr", "pct2"),
                             ("CPC", "cpc", "money2"), ("广告 CVR", "ad_cvr", "pct2"), ("广告订单", "ad_orders", "int"), ("广告销量", "ad_units", "int"),
                             ("广告销售额", "ad_sales", "money"), ("广告花费", "ad_spend", "money"),
                             ("ACOS", "acos", "pct"), ("CPA", "cpa", "money2")):
        rows.append([label, fmt_value(m.get(key), kind, currency),
                     fmt_value(spu.get("last", {}).get(key), kind, currency) if spu.get("has_last") else "—",
                     (wow.get(key) or {}).get("label", "—")])
    lines += [_md_table(["指标", "本周", "上周", "变化"], rows, [1, 2, 3]), ""]

    daily = spu.get("daily") or []
    if daily:
        rows = [[d.get("date"), f"{num(d.get('ad_impressions')):,.0f}", f"{num(d.get('ad_clicks')):,.0f}",
                 pct(d.get("ad_ctr"), 2), f"${num(d.get('cpc')):,.2f}", pct(d.get("ad_cvr"), 2), f"{num(d.get('ad_units')):,.0f}"] for d in daily]
        lines += ["**每日广告表现**", "", _md_table(["日期", "曝光", "点击", "CTR", "CPC", "CVR", "广告销量"], rows, [1, 2, 3, 4, 5, 6]), ""]

    campaigns = (spu.get("ads") or {}).get("campaigns") or []
    if campaigns:
        rows = [[c.get("name"), money(c.get("budget"), currency) if c.get("budget") else "—", money(c.get("spend"), currency),
                 pct(c.get("budget_used"), 0) if c.get("budget_used") is not None else "—", pct(c.get("cvr"), 2),
                 f"${num(c.get('cpa')):,.2f}" if c.get("cpa") else "—"] for c in campaigns]
        lines += ["**广告活动**", "", _md_table(["广告活动", "预算", "花费", "预算使用", "CVR", "CPA"], rows, [1, 2, 3, 4, 5]), ""]

    words = (spu.get("ads") or {}).get("keywords") or []
    if words:
        rows = [[w.get("keyword"), f"{num(w.get('clicks')):,.0f}", money(w.get("spend"), currency), pct(w.get("spend_share"), 1), pct(w.get("cvr"), 1)] for w in words]
        lines += ["**关键词花费（跨活动）**", "", _md_table(["关键词", "点击", "花费", "花费占比", "CVR"], rows, [1, 2, 3, 4]), ""]

    for parent in spu.get("parents") or []:
        kw = parent.get("keywords") or {}
        est = bool(kw.get("estimated_share"))
        src = "SIF" if kw.get("source") == "sif" else "Sorftime"
        lines += [f"### C 关键词结构 · {parent['asin']}（数据源 {src}{'，流量占比为估算' if est else ''}）", "",
                  "**① 自然位**", "", _md_kw(kw.get("organic") or [], "organic", est),
                  "**② 广告位**", "", _md_kw(kw.get("ads") or [], "ads", est),
                  "**③ 流量前 80%**", "", _md_kw(kw.get("top80") or [], "top80", est)]
        if est:
            lines += ["> 流量占比为估算：月搜索量 × 位置权重，在本次抓取词内归一化，不等同真实流量份额。", ""]

    comp = data.get("competitor") or {}
    lines += ["## 三、竞品", ""]
    if comp.get("asin"):
        lines += [f"### {comp['asin']}{(' · ' + comp['brand']) if comp.get('brand') else ''}", ""]
        rows = [["划线价", f"${num(comp.get('list_price')):,.2f}" if comp.get("list_price") else "—", ""],
                ["现价", f"${num(comp.get('price')):,.2f}" if comp.get("price") else "—", _price_delta(comp)],
                ["折扣", _discount(comp), ""],
                ["活动", "有券/促销" if comp.get("deal") else "无", ""],
                ["评分", f"{num(comp.get('rating')):.1f}" if comp.get("rating") else "—", _num_delta(comp.get("rating_delta"), 1)],
                ["评论数", f"{num(comp.get('reviews')):,.0f}" if comp.get("reviews") else "—", _num_delta(comp.get("reviews_delta"), 0)],
                ["变体数", f"{num(comp.get('variation_count')):,.0f}" if comp.get("variation_count") else "—", _variation_delta(comp)],
                ["月销（估）", f"{num(comp.get('monthly_sales')):,.0f}" if comp.get("monthly_sales") else "—", ""]]
        lines += [_md_table(["指标", "数值", "变化"], rows), ""]
        ckw = comp.get("keywords") or {}
        if ckw.get("terms"):
            est = bool(ckw.get("estimated_share"))
            lines += ["**竞品流量结构（前 80%）**", "", "**① 自然位**", "", _md_kw(ckw.get("organic80") or [], "organic", est),
                      "**② 广告位**", "", _md_kw(ckw.get("ads80") or [], "ads", est),
                      "**③ 流量前 80%**", "", _md_kw(ckw.get("top80") or [], "top80", est)]
    else:
        lines += ["未配置竞品链接。", ""]

    lines += ["---", "",
              f"数据源：领星 ERP（销量、广告、利润）；{meta.get('keywords_source', '')}（关键词与位置）。",
              "口径：周为自然周（周一至周日）；销售额为商品销售额，未扣退款。"]
    return "\n".join(lines)


def render_markdown_report(datas: List[Dict[str, Any]]) -> str:
    if not datas:
        raise ValueError("没有可渲染的 SPU 数据")
    first = datas[0]["meta"]
    sites = {d["meta"].get("site_label") or d["meta"].get("site") for d in datas}
    multi_site = len(sites) > 1
    site_label = "多站点" if multi_site else sites.pop()
    title = f"{site_label} · {first['iso_week']}经营周报"
    lines = [f"# {title}", "",
             f"{first['week_label']}（{first['iso_week']}） · SPU {len(datas)} 个 · 数据源 领星 / {first.get('keywords_source', '')}", ""]
    if first.get("demo"):
        lines += ["> 演示数据：仅用于确认版式与口径，不是真实经营数据。", ""]
    lines += ["## 本周结论", ""]
    for line in _combined_findings(datas):
        if "｜" in line:
            label, text = line.split("｜", 1)
            lines.append(f"- **{label}**　{text}")
        else:
            lines.append(f"- {line}")
    lines.append("")

    rows = []
    total_revenue = total_target = total_units = total_profit = 0.0
    for data in datas:
        o = data["overview"][0]
        row = [o["spu"]]
        if multi_site:
            row.append(data["meta"].get("site_label") or data["meta"].get("site"))
        row += [f"{num(o['units']):,.0f}", money(o["revenue"]),
                money(o["target"]) if o.get("target") else "—",
                pct(o["attainment"]) if o.get("attainment") is not None else "—",
                pct(o.get("target_margin")) if o.get("target_margin") is not None else "—",
                pct(o.get("actual_margin")) if o.get("actual_margin") is not None else "—"]
        rows.append(row)
        total_units += num(o["units"])
        total_revenue += num(o["revenue"])
        total_target += num(o.get("target"))
        total_profit += num(o.get("profit"))
    if len(datas) > 1:
        row = ["合计"] + ([""] if multi_site else [])
        row += [f"{total_units:,.0f}", money(total_revenue), money(total_target),
                pct(safe_div(total_revenue, total_target)), "—", pct(safe_div(total_profit, total_revenue))]
        rows.append(row)
    headers = ["SPU"] + (["站点"] if multi_site else []) + ["实际销量", "实际销售额", "周目标", "达成率", "目标利润率", "实际利润率"]
    right = list(range(len(headers) - 6, len(headers)))
    lines += ["## 一、总览", "",
              _md_table(headers, rows, right), "",
              "## 二、分 SPU 分析", ""]

    for index, data in enumerate(datas, start=1):
        md = render_markdown(data)
        body = md[md.index("## 二、"):]
        body = body.split("\n---\n")[0]
        body = re.sub(r"^(#{2,4}) ", lambda m: "#" * (len(m.group(1)) + 1) + " ", body, flags=re.M)
        spu = data["spus"][0]
        body = re.sub(r"^### 二、.*$", f"### {index}. {spu['spu']} · {data['meta']['site_label']}", body, count=1, flags=re.M)
        lines += [body.rstrip(), ""]
    return "\n".join(lines)
