"""Momentum analytics (daily gains, week over week, spikes, benchmarks, milestones).

Execute with: python -m unittest discover -s backend/tests -p 'test_momentum.py'
(needs TEST_DATABASE_URL, see support.py).
"""
import unittest
from datetime import date, timedelta

from support import ApiTestCase, requires_postgres

TODAY = date.today()


@requires_postgres
class Momentum(ApiTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = None

    def setUp(self):
        if Momentum.token:
            return
        body = self.register("momentum@example.com")
        token, user_id = body["token"], body["user"]["user_id"]
        profile = self.profile_id(token)
        base = {"profile_id": profile, "owner_id": user_id}
        releases, content, snaps = [], [], []

        def release(rid, day0):
            releases.append({"id": rid, "title": rid, "release_date": day0.isoformat(), **base})

        def item(cid, rid, platform="youtube"):
            content.append({"id": cid, "release_id": rid, "title": cid, "platform": platform, **base})

        def observe(cid, rid, day0, values):
            for d, reach in values.items():
                snaps.append({"id": f"{cid}_{d}", "content_item_id": cid, "release_id": rid,
                              "date": (day0 + timedelta(days=d)).isoformat(), "source": "manual",
                              "reach": reach, "views": reach, "engagement": reach // 10,
                              "followers": reach // 100, "profile_id": base["profile_id"]})

        # Two earlier releases: 800 and 1,000 by Day 7, 2,900 and 3,000 by Day 28.
        b0, c0 = TODAY - timedelta(days=100), TODAY - timedelta(days=70)
        release("rel_b", b0), item("b1", "rel_b")
        observe("b1", "rel_b", b0, {d: 100 * (d + 1) for d in range(29)})
        release("rel_c", c0), item("c1", "rel_c")
        observe("c1", "rel_c", c0, {**{d: 100 * (d + 1) + 200 for d in range(28)}, 28: 3000})

        # The latest release gains 200 a day, is not observed on Day 20, and
        # gains 1,000 on its last observed day (yesterday). A second item joins
        # on Day 10 already at 1,000 and never grows.
        a0 = TODAY - timedelta(days=40)
        release("rel_a", a0), item("a1", "rel_a"), item("a2", "rel_a", "soundcloud")
        a1 = {d: 200 * (d + 1) for d in range(39) if d != 20}
        a1[39] = a1[38] + 1000
        observe("a1", "rel_a", a0, a1)
        observe("a2", "rel_a", a0, {d: 1000 for d in range(10, 40)})

        from database import db

        async def load():
            await db.insert_many("releases", releases)
            await db.insert_many("content_items", content)
            await db.insert_many("metric_snapshots", snaps)

        self.run_db(load)
        Momentum.token, Momentum.profile, Momentum.a0 = token, profile, a0

    def get(self, path):
        response = self.client.get(path, headers=self.auth(self.token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def day(self, n):
        return (self.a0 + timedelta(days=n)).isoformat()

    def test_daily_gains_skip_unobserved_days_and_late_joiners(self):
        body = self.get(f"/api/analytics/release-momentum/rel_a")
        by_day = {p["date"]: p["value"] for p in body["daily"]}
        self.assertEqual(by_day[self.day(0)], 200)            # Day 0 counts its first total
        self.assertEqual(by_day[self.day(10)], 200)           # a2 joining at 1,000 is not a gain
        self.assertNotIn(self.day(20), by_day)                # not observed
        self.assertNotIn(self.day(21), by_day)                # no observed day before it
        self.assertEqual(by_day[self.day(39)], 1000)
        avg = {p["date"]: p["avg7"] for p in body["daily"]}
        self.assertIsNone(avg[self.day(0)])                   # fewer than 4 days behind it
        self.assertEqual(avg[self.day(9)], 200)

    def test_week_over_week(self):
        week = self.get(f"/api/analytics/momentum?profile_id={self.profile}")["week"]
        self.assertEqual(week["through"], self.day(39))
        self.assertEqual((week["this_week"], week["this_week_days"]), (6 * 200 + 1000, 7))
        self.assertEqual((week["last_week"], week["last_week_days"]), (7 * 200, 7))
        self.assertEqual(week["change"], round(800 / 1400, 3))

    def test_spike_is_flagged(self):
        alerts = self.get(f"/api/analytics/momentum?profile_id={self.profile}")["alerts"]
        self.assertEqual(alerts, [{"release_id": "rel_a", "title": "rel_a", "date": self.day(39),
                                   "gained": 1000, "usual": 200, "ratio": 5.0}])

    def test_benchmarks_compare_only_with_earlier_releases(self):
        marks = self.get(f"/api/analytics/momentum?profile_id={self.profile}")["benchmarks"]
        a = marks["rel_a"]
        self.assertEqual(a["day7"], {"value": 1600, "usual": 900, "compared_with": 2, "index": 1.78})
        self.assertEqual((a["day28"]["value"], a["day28"]["usual"]), (6800, 2950))
        # The first release has nothing to be compared with.
        self.assertEqual(marks["rel_b"]["day7"]["compared_with"], 0)
        self.assertIsNone(marks["rel_b"]["day7"]["index"])

    def test_milestones(self):
        body = self.get(f"/api/analytics/momentum?profile_id={self.profile}")
        recent = [(m["release_id"], m["threshold"], m["day"]) for m in body["milestones"]]
        self.assertIn(("rel_a", 1000, 4), recent)
        self.assertNotIn(10000, {m[1] for m in recent})  # 9,800 at most
        self.assertNotIn("rel_b", {m[0] for m in recent})  # older than 60 days
        release = self.get(f"/api/analytics/release-momentum/rel_b")
        self.assertEqual([m["threshold"] for m in release["milestones"]], [1000])

    def test_quality(self):
        quality = {q["release_id"]: q for q in self.get(f"/api/analytics/momentum?profile_id={self.profile}")["quality"]}
        self.assertEqual(quality["rel_b"]["engagement_rate"], 0.1)
        self.assertEqual(quality["rel_b"]["followers_per_1k"], 10.0)

    def test_other_users_cannot_read_it(self):
        other = self.register("momentum-other@example.com")["token"]
        response = self.client.get("/api/analytics/release-momentum/rel_a", headers=self.auth(other))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(f"/api/analytics/momentum?profile_id={self.profile}", headers=self.auth(other))
        self.assertIn(response.status_code, (403, 404))


if __name__ == "__main__":
    unittest.main()
