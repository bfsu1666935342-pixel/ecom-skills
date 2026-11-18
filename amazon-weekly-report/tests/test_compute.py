"""Unit tests for the weekly report engine (stdlib unittest)."""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wr import compute
from wr.render import render_html, render_markdown


def week_block(units=1000, revenue=50000, sessions=30000, clicks=15000, impressions=2_000_000,
               orders=950, ad_impressions=500_000, ad_clicks=8000, ad_spend=4000,
               ad_orders=500, ad_sales=21000, returns=40, refunds=1200, profit=0, days=7):
    aggregate = {
        "units": units, "revenue": revenue, "sessions": sessions, "clicks": clicks,
        "impressions": impressions, "orders": orders, "ad_impressions": ad_impressions,
        "ad_clicks": ad_clicks, "ad_spend": ad_spend, "ad_orders": ad_orders,
        "ad_sales": ad_sales, "returns": returns, "refunds": refunds, "profit": profit,
    }
    daily = []
    for i in range(days):
        day = {k: v / days for k, v in aggregate.items()}
        day["date"] = (dt.date(2026, 11, 9) + dt.timedelta(days=i)).isoformat()
        daily.append(day)
    return {"aggregate": aggregate, "daily": daily, "row_count": days}


class TargetTests(unittest.TestCase):
    def test_month_proration(self):
        entry = {"monthly": {"2026-11": 30000}, "default_monthly": 30000}
        # 2026-11-09 .. 2026-11-15 all inside a 30-day month
        self.assertAlmostEqual(compute.weekly_target(entry, dt.date(2026, 11, 9)), 7000, places=2)

    def test_cross_month(self):
        entry = {"monthly": {"2026-01": 31000, "2026-02": 28000}, "default_monthly": 0}
        # Mon 2026-01-26 .. Sun 2026-02-01: 6 days Jan (31) + 1 day Feb (28)
        expected = 31000 * 6 / 31 + 28000 * 1 / 28
        self.assertAlmostEqual(compute.weekly_target(entry, dt.date(2026, 1, 26)), expected, places=2)

    def test_override(self):
        entry = {"weekly_overrides": {"2026-11-09": 12345}, "default_monthly": 99999}
        self.assertEqual(compute.weekly_target(entry, dt.date(2026, 11, 9)), 12345)


class DerivedTests(unittest.TestCase):
    def test_rates(self):
        raw = week_block()["aggregate"]
        d = compute.derived(raw)
        self.assertAlmostEqual(d["ctr"], 15000 / 2_000_000)
        self.assertAlmostEqual(d["cvr"], 950 / 30000)
        self.assertAlmostEqual(d["ad_cvr"], 500 / 8000)
        self.assertAlmostEqual(d["cpc"], 4000 / 8000)
        self.assertAlmostEqual(d["acoas"], 4000 / 50000)
        self.assertAlmostEqual(d["ad_order_share"], 500 / 950)
        self.assertAlmostEqual(d["return_rate"], 40 / 1000)


class ProfitTests(unittest.TestCase):
    def test_computed_profit(self):
        entry = {"target_margin": 0.2, "cost": {"unit_cost": 10, "first_leg": 2, "fba_fee": 5, "referral_rate": 0.15, "other_per_unit": 1}}
        raw = week_block()["aggregate"]
        p = compute.profit_block(entry, raw, raw["revenue"], raw["units"], raw["ad_spend"], raw["refunds"])
        expected = 50000 - 10 * 1000 - 2 * 1000 - 50000 * 0.15 - 5 * 1000 - 1 * 1000 - 4000 - 1200
        self.assertAlmostEqual(p["amount"], expected)
        self.assertEqual(p["source"], "computed")

    def test_lingxing_profit_wins(self):
        entry = {"target_margin": 0.2, "cost": {"unit_cost": 10}}
        raw = week_block(profit=7777)["aggregate"]
        p = compute.profit_block(entry, raw, raw["revenue"], raw["units"], raw["ad_spend"], raw["refunds"])
        self.assertEqual(p["amount"], 7777)
        self.assertEqual(p["source"], "lingxing")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.product = {
            "id": "66D50F", "spu": "66D50F", "site": "US", "title": "Demo",
            "parents": [{"asin": "B0XXXXXXXX"}, {"asin": "B0YYYYYYYY"}],
            "competitor": {"asin": "B0B41X9SMT"},
        }
        terms = [
            {"keyword": "drafting chair", "search_volume": 100000, "traffic_share": 0.6, "cum_share": 0.6, "organic_page": 1, "organic_pos": 2, "ad_page": 1, "ad_pos": 4},
            {"keyword": "tall office chair", "search_volume": 20000, "traffic_share": 0.3, "cum_share": 0.9, "organic_page": 1, "organic_pos": 6, "ad_page": 1, "ad_pos": 8},
        ]
        kw = {"source": "sorftime", "estimated_share": True, "terms": terms, "organic": terms, "ads": terms, "top80": terms[:1], "total_terms": 2, "cover_count": 1, "coverage": 0.6}
        self.keywords = {"B0XXXXXXXX": kw, "B0YYYYYYYY": {**kw, "notes": []}}
        self.lingxing = {
            "this": week_block(), "last": week_block(units=900, revenue=45000, sessions=29000, clicks=14500, impressions=1_950_000, orders=880, ad_spend=3800, ad_clicks=7800, ad_orders=470, ad_sales=20000, ad_impressions=480_000, returns=35, refunds=1100),
            "campaigns": [{"name": "SP-A", "budget": 1000, "spend": 800, "clicks": 2000, "orders": 120, "sales": 5000, "impressions": 100000}],
            "keywords": [{"keyword": "drafting chair", "clicks": 2000, "spend": 800, "orders": 120, "sales": 5000}],
            "errors": {},
        }
        self.targets = {"66D50F": {"monthly": {"2026-11": 300000}, "default_monthly": 300000, "target_margin": 0.2,
                                   "cost": {"unit_cost": 10, "first_leg": 2, "fba_fee": 5, "referral_rate": 0.15, "other_per_unit": 1}}}
        self.competitor = {"asin": "B0B41X9SMT", "price": 40, "list_price": 50, "rating": 4.3, "reviews": 100, "variation_count": 10,
                           "monthly_sales": 500, "deal": False, "price_delta": -2, "rating_delta": 0, "reviews_delta": 5,
                           "variation_delta": 1, "compared_to": "2026-11-01",
                           "keywords": {"source": "sorftime", "estimated_share": True, "terms": terms, "organic80": terms, "ads80": terms, "top80": terms}}

    def test_build_shape_and_multi_parent(self):
        data = compute.build(self.product, dt.date(2026, 11, 9), self.lingxing, self.keywords, self.competitor,
                             self.targets, {"currency": "USD", "thresholds": {}}, demo=True)
        spu = data["spus"][0]
        self.assertEqual(len(spu["parents"]), 2)
        self.assertEqual(spu["parents"][1]["keywords"]["terms"][0]["keyword"], "drafting chair")
        self.assertAlmostEqual(data["overview"][0]["attainment"], 50000 / 70000, places=4)
        self.assertAlmostEqual(data["overview"][0]["actual_margin"], data["overview"][0]["profit"] / 50000, places=4)
        self.assertTrue(data["meta"]["demo"])
        self.assertTrue(data["flags"])

    def test_render_contains_sections(self):
        data = compute.build(self.product, dt.date(2026, 11, 9), self.lingxing, self.keywords, self.competitor,
                             self.targets, {"currency": "USD", "thresholds": {}}, demo=True)
        html = render_html(data, demo=True)
        for token in ("本周结论", "总览", "整体数据", "广告数据", "关键词结构", "B0YYYYYYYY", "竞品"):
            self.assertIn(token, html)
        self.assertNotIn("None", html)
        md = render_markdown(data)
        self.assertIn("## 一、总览", md)
        self.assertIn("### C 关键词结构", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
