"""The API end to end against a real PostgreSQL database.

Execute with: python -m unittest discover -s backend/tests -p 'test_api.py'
(needs TEST_DATABASE_URL, see support.py).
"""
import random
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from support import ApiTestCase, requires_postgres


# ---------------------------------------------------------------------------
# The analytics as they were computed in Python before the move to SQL. The
# SQL versions must give the same answers on the same rows.
# ---------------------------------------------------------------------------
METRICS = ["views", "plays", "likes", "comments", "shares", "reach", "engagement", "followers"]


def _priority(s):
    return {"youtube_analytics_history": 30, "youtube_api": 20}.get(s.get("source"), 10)


def _dedupe(snaps):
    chosen = {}
    for s in snaps:
        key = (s["content_item_id"], s["date"])
        if key not in chosen or _priority(s) > _priority(chosen[key]):
            chosen[key] = s
    return chosen


def reference_release_totals(content, snaps):
    latest = {}
    for s in _dedupe(snaps).values():
        cid = s["content_item_id"]
        if cid not in latest or s["date"] > latest[cid]["date"]:
            latest[cid] = s
    totals = {k: 0 for k in METRICS}
    per_platform = {}
    last = None
    for c in content:
        snap = latest.get(c["id"])
        if not snap:
            continue
        plat = per_platform.setdefault(c["platform"], {k: 0 for k in METRICS})
        for k in METRICS:
            totals[k] += snap[k]
            plat[k] += snap[k]
        last = snap["date"] if last is None or snap["date"] > last else last
    return {"totals": totals, "per_platform": per_platform, "content_count": len(content), "last_synced": last}


def reference_timeseries(snaps, metric):
    by_date = {}
    for s in _dedupe(snaps).values():
        by_date[s["date"]] = by_date.get(s["date"], 0) + s[metric]
    return [{"date": d, "value": by_date[d]} for d in sorted(by_date)]


def reference_race(release, snaps, metric, max_day):
    day0 = date.fromisoformat(release["release_date"])
    by_off = {}
    for s in _dedupe(snaps).values():
        off = (date.fromisoformat(s["date"]) - day0).days
        if 0 <= off <= max_day:
            by_off[off] = by_off.get(off, 0) + s[metric]
    return [{"day": d, "value": by_off[d]} for d in sorted(by_off)]


@requires_postgres
class AuthAndSessions(ApiTestCase):
    def test_register_login_me(self):
        body = self.register("a@example.com")
        me = self.client.get("/api/auth/me", headers=self.auth(body["token"]))
        self.assertEqual(me.json()["email"], "a@example.com")
        login = self.client.post("/api/auth/login", json={"email": "A@Example.com", "password": "Passw0rd!long"})
        self.assertEqual(login.status_code, 200)

    def test_new_account_gets_a_workspace_and_profile(self):
        token = self.register("ws@example.com", name="WS")["token"]
        workspaces = self.client.get("/api/workspaces", headers=self.auth(token)).json()["workspaces"]
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["profiles"][0]["name"], "WS")

    def test_duplicate_email_is_refused(self):
        self.register("dup@example.com")
        response = self.client.post("/api/auth/register",
                                    json={"email": "DUP@example.com", "password": "Passw0rd!long", "name": "x"})
        self.assertEqual(response.status_code, 400)

    def test_short_password_is_refused(self):
        response = self.client.post("/api/auth/register",
                                    json={"email": "short@example.com", "password": "1234567", "name": "x"})
        self.assertEqual(response.status_code, 422)

    def test_logout_ends_the_session(self):
        token = self.register("out@example.com")["token"]
        self.assertEqual(self.client.post("/api/auth/logout", headers=self.auth(token)).status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/auth/me", headers=self.auth(token)).status_code, 401)

    def test_logout_ends_only_that_session(self):
        self.register("two@example.com")
        first = self.client.post("/api/auth/login", json={"email": "two@example.com", "password": "Passw0rd!long"}).json()["token"]
        second = self.client.post("/api/auth/login", json={"email": "two@example.com", "password": "Passw0rd!long"}).json()["token"]
        self.client.post("/api/auth/logout", headers=self.auth(first))
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/auth/me", headers=self.auth(second)).status_code, 200)

    def test_token_without_a_session_is_refused(self):
        import jwt, os
        body = self.register("legacy@example.com")
        legacy = jwt.encode({"sub": body["user"]["user_id"], "type": "access", "exp": 9999999999},
                            os.environ["JWT_SECRET"], algorithm="HS256")
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/auth/me", headers=self.auth(legacy)).status_code, 401)

    def test_wrong_password_then_lockout(self):
        self.register("lock@example.com")
        for _ in range(5):
            r = self.client.post("/api/auth/login", json={"email": "lock@example.com", "password": "wrong-password"})
            self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/auth/login", json={"email": "lock@example.com", "password": "Passw0rd!long"})
        self.assertEqual(r.status_code, 429)

    def test_invite_codes_gate_sign_up(self):
        with patch.dict("os.environ", {"BETA_INVITE_CODES": "alpha-123, beta-456"}):
            self.assertEqual(self.client.get("/api/auth/signup-policy").json(), {"invite_required": True})
            no_code = self.client.post("/api/auth/register",
                                       json={"email": "inv@example.com", "password": "Passw0rd!long", "name": "x"})
            self.assertEqual(no_code.status_code, 403)
            wrong = self.client.post("/api/auth/register", json={
                "email": "inv@example.com", "password": "Passw0rd!long", "name": "x", "invite_code": "nope"})
            self.assertEqual(wrong.status_code, 403)
            self.register("inv@example.com", invite_code="beta-456")
        self.assertEqual(self.client.get("/api/auth/signup-policy").json(), {"invite_required": False})

    def test_expired_state_is_cleaned_up(self):
        import server
        self.sql("INSERT INTO oauth_states (nonce, type, expires_at) VALUES ('old', 't', now() - interval '1 minute'),"
                 " ('new', 't', now() + interval '1 minute')")
        self.run_db(server.cleanup_expired_state)
        self.assertEqual([r["nonce"] for r in self.sql("SELECT nonce FROM oauth_states")], ["new"])


@requires_postgres
class DataIsolation(ApiTestCase):
    def test_other_users_data_is_not_found(self):
        owner = self.register("owner@example.com")["token"]
        intruder = self.register("intruder@example.com")["token"]
        profile = self.profile_id(owner)
        rel = self.client.post("/api/releases", headers=self.auth(owner), json={
            "profile_id": profile, "title": "Mine", "release_date": "2026-01-01"}).json()["release"]
        h = self.auth(intruder)
        self.assertEqual(self.client.get(f"/api/releases/{rel['id']}", headers=h).status_code, 404)
        self.assertEqual(self.client.get(f"/api/releases?profile_id={profile}", headers=h).status_code, 404)
        self.assertEqual(self.client.get(f"/api/analytics/overview?profile_id={profile}", headers=h).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/releases/{rel['id']}", headers=h, json={"title": "x"}).status_code, 404)

    def test_unauthenticated_requests_are_refused(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/workspaces").status_code, 401)


@requires_postgres
class Releases(ApiTestCase):
    def setUp(self):
        self.client.cookies.clear()

    def test_create_update_and_validate(self):
        token = self.register(f"rel{random.random()}@example.com")["token"]
        profile = self.profile_id(token)
        h = self.auth(token)
        bad = self.client.post("/api/releases", headers=h, json={
            "profile_id": profile, "title": "Bad", "release_date": "01/02/2026"})
        self.assertEqual(bad.status_code, 422)
        rel = self.client.post("/api/releases", headers=h, json={
            "profile_id": profile, "title": "Good", "release_date": "2026-02-01"}).json()["release"]
        self.assertEqual(rel["release_date"], "2026-02-01")
        updated = self.client.patch(f"/api/releases/{rel['id']}", headers=h,
                                    json={"title": "Better", "release_date": "2026-02-03"}).json()["release"]
        self.assertEqual((updated["title"], updated["release_date"]), ("Better", "2026-02-03"))
        self.assertIsNotNone(updated["updated_at"])

    def test_profile_creation_turns_workspace_into_manager(self):
        token = self.register(f"mgr{random.random()}@example.com")["token"]
        h = self.auth(token)
        ws = self.client.get("/api/workspaces", headers=h).json()["workspaces"][0]
        self.client.post("/api/profiles", headers=h, json={"workspace_id": ws["id"], "name": "Second"})
        ws = self.client.get("/api/workspaces", headers=h).json()["workspaces"][0]
        self.assertEqual(ws["type"], "manager")
        self.assertEqual(len(ws["profiles"]), 2)


@requires_postgres
class CsvImport(ApiTestCase):
    def commit(self, token, profile, rows, **overrides):
        body = {
            "profile_id": profile, "platform": "spotify", "release_title": "Imported",
            "release_date": "2026-03-01", "mapping": {"date": "Date", "plays": "Streams"}, "rows": rows,
        }
        body.update(overrides)
        return self.client.post("/api/csv/commit", headers=self.auth(token), json=body)

    def test_commit_creates_release_content_and_snapshots(self):
        token = self.register("csv@example.com")["token"]
        profile = self.profile_id(token)
        rows = [{"Date": f"2026-03-0{d}", "Streams": str(100 * d)} for d in range(1, 6)]
        result = self.commit(token, profile, rows).json()
        self.assertEqual(result["snapshots"], 5)
        detail = self.client.get(f"/api/releases/{result['release_id']}", headers=self.auth(token)).json()
        self.assertEqual(detail["rollup"]["totals"]["plays"], 500)
        self.assertEqual(detail["content"][0]["last_synced"], "2026-03-05")

    def test_repeated_dates_keep_one_row_per_day(self):
        token = self.register("csvdup@example.com")["token"]
        profile = self.profile_id(token)
        rows = [{"Date": "2026-03-01", "Streams": "10"}, {"Date": "2026-03-01", "Streams": "30"},
                {"Date": "2026-03-02", "Streams": "40"}]
        result = self.commit(token, profile, rows).json()
        self.assertEqual(result["snapshots"], 2)
        snaps = self.sql("SELECT date, plays FROM metric_snapshots WHERE release_id = $1 ORDER BY date",
                         result["release_id"])
        self.assertEqual([(s["date"], s["plays"]) for s in snaps], [("2026-03-01", 30), ("2026-03-02", 40)])

    def test_unreadable_dates_are_rejected_without_writing_anything(self):
        token = self.register("csvbad@example.com")["token"]
        profile = self.profile_id(token)
        before = self.sql("SELECT count(*) AS n FROM releases")[0]["n"]
        response = self.commit(token, profile, [{"Date": "03/01/2026", "Streams": "5"}])
        self.assertEqual(response.status_code, 422)
        self.assertIn("YYYY-MM-DD", response.json()["detail"])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM releases")[0]["n"], before)

    def upload(self, token, profile, content, name="export.csv", header=True):
        headers = self.auth(token)
        if header:
            headers["X-Requested-With"] = "XobaMetrics"
        return self.client.post("/api/csv/upload", headers=headers, data={"profile_id": profile},
                                files={"file": (name, content, "text/csv")})

    def test_upload_guards(self):
        token = self.register("guards@example.com")["token"]
        profile = self.profile_id(token)
        self.client.cookies.clear()
        self.assertEqual(self.upload(token, profile, "date,streams\n", header=False).status_code, 403)
        self.assertEqual(self.upload(token, profile, "date,streams\n", name="export.txt").status_code, 400)
        big = "date,streams\n" + "2026-01-01,1\n" * 500_000
        self.assertEqual(self.upload(token, profile, big).status_code, 413)
        rows = [{"Date": "2026-03-01", "Streams": "1"}] * 5001
        self.assertEqual(self.commit(token, profile, rows).status_code, 413)

    def test_upload_parses_and_records_the_file(self):
        token = self.register("upload@example.com")["token"]
        profile = self.profile_id(token)
        csv = "date,streams\n" + "\n".join(f"2026-01-{d:02d},{d}" for d in range(1, 11))
        response = self.upload(token, profile, csv)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["row_count"], 10)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM files")[0]["n"], 1)


@requires_postgres
class AnalyticsMatchThePythonVersion(ApiTestCase):
    """Seed awkward data straight into the tables, then compare with the old algorithm."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = None

    def setUp(self):
        if AnalyticsMatchThePythonVersion.token:
            return
        body = self.register("analytics@example.com")
        token = body["token"]
        user_id = body["user"]["user_id"]
        profile = self.profile_id(token)
        ws = self.client.get("/api/workspaces", headers=self.auth(token)).json()["workspaces"][0]["id"]
        rnd = random.Random(7)
        releases, content, snaps = [], [], []
        for r in range(3):
            day0 = date(2026, 1, 1) + timedelta(days=20 * r)
            releases.append({"id": f"rel_{r}", "profile_id": profile, "workspace_id": ws, "owner_id": user_id,
                             "title": f"Release {r}", "release_date": day0.isoformat()})
            for c in range(3):
                cid = f"ci_{r}_{c}"
                platform = ["youtube", "soundcloud", "spotify"][c]
                content.append({"id": cid, "release_id": f"rel_{r}", "profile_id": profile,
                                "workspace_id": ws, "owner_id": user_id, "title": cid, "platform": platform})
                # Observations start before Day 0 for one item and have gaps.
                for d in range(-3 if c == 0 else 0, 40, rnd.choice([1, 2, 3])):
                    sources = ["manual"]
                    if platform == "youtube":
                        sources = rnd.sample(["youtube_api", "youtube_analytics_history", "manual"], k=rnd.randint(1, 3))
                    for source in sources:
                        base = (d + 5) * 100 + c * 7 + {"youtube_analytics_history": 3, "youtube_api": 2}.get(source, 1)
                        snaps.append({
                            "id": f"snap_{cid}_{d}_{source}", "content_item_id": cid, "release_id": f"rel_{r}",
                            "profile_id": profile, "date": (day0 + timedelta(days=d)).isoformat(), "source": source,
                            **{k: base * (i + 1) for i, k in enumerate(METRICS)},
                        })
        # A release with content but no observations, and one with nothing.
        releases.append({"id": "rel_empty", "profile_id": profile, "workspace_id": ws, "owner_id": user_id,
                         "title": "Empty", "release_date": "2026-05-01"})
        content.append({"id": "ci_unobserved", "release_id": "rel_empty", "profile_id": profile,
                        "workspace_id": ws, "owner_id": user_id, "title": "unobserved", "platform": "tiktok"})
        from database import db

        async def load():
            async with db.transaction():
                await db.insert_many("releases", releases)
                await db.insert_many("content_items", content)
                await db.insert_many("metric_snapshots", snaps)

        self.run_db(load)
        cls = AnalyticsMatchThePythonVersion
        cls.token, cls.profile, cls.releases, cls.content, cls.snaps = token, profile, releases, content, snaps

    def get(self, path):
        response = self.client.get(path, headers=self.auth(self.token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_release_totals(self):
        for rel in self.releases:
            content = [c for c in self.content if c["release_id"] == rel["id"]]
            snaps = [s for s in self.snaps if s["release_id"] == rel["id"]]
            got = self.get(f"/api/releases/{rel['id']}")["rollup"]
            self.assertEqual(got, reference_release_totals(content, snaps), rel["id"])

    def test_release_list_and_overview(self):
        listed = {r["id"]: r for r in self.get(f"/api/releases?profile_id={self.profile}")["releases"]}
        overview = self.get(f"/api/analytics/overview?profile_id={self.profile}")
        grand = {k: 0 for k in METRICS}
        for rel in self.releases:
            expected = reference_release_totals(
                [c for c in self.content if c["release_id"] == rel["id"]],
                [s for s in self.snaps if s["release_id"] == rel["id"]],
            )
            self.assertEqual(listed[rel["id"]]["reach"], expected["totals"]["reach"])
            self.assertEqual(listed[rel["id"]]["content_count"], expected["content_count"])
            for k in METRICS:
                grand[k] += expected["totals"][k]
        self.assertEqual(overview["totals"], grand)
        self.assertEqual(overview["release_count"], 4)
        self.assertEqual(overview["top_release"]["reach"], max(r["reach"] for r in listed.values()))

    def test_timeseries(self):
        for metric in ("reach", "plays", "followers"):
            got = self.get(f"/api/analytics/release-timeseries/rel_1?metric={metric}")["series"]
            self.assertEqual(got, reference_timeseries([s for s in self.snaps if s["release_id"] == "rel_1"], metric))

    def test_release_race(self):
        ids = "rel_2,rel_missing,rel_0,rel_empty"
        got = self.get(f"/api/analytics/release-race?profile_id={self.profile}&release_ids={ids}&metric=engagement&max_day=30")
        self.assertEqual([r["release_id"] for r in got["releases"]], ["rel_2", "rel_0", "rel_empty"])
        # Colours follow the requested position, as before.
        self.assertEqual(got["releases"][1]["color"], "#FBBF24")
        for r in got["releases"]:
            rel = next(x for x in self.releases if x["id"] == r["release_id"])
            expected = reference_race(rel, [s for s in self.snaps if s["release_id"] == rel["id"]], "engagement", 30)
            self.assertEqual(r["series"], expected, r["release_id"])

    def test_unknown_metric_is_rejected(self):
        response = self.client.get("/api/analytics/release-timeseries/rel_1?metric=password_hash",
                                   headers=self.auth(self.token))
        self.assertEqual(response.status_code, 422)


@requires_postgres
class MergeAndMatch(ApiTestCase):
    def make(self, token, profile, title, day, platform, streams):
        rows = [{"Date": day, "Streams": str(streams)}]
        body = {"profile_id": profile, "platform": platform, "release_title": title, "release_date": day,
                "mapping": {"date": "Date", "plays": "Streams"}, "rows": rows}
        return self.client.post("/api/csv/commit", headers=self.auth(token), json=body).json()["release_id"]

    def test_merge_moves_content_and_snapshots_then_deletes_sources(self):
        token = self.register("merge@example.com")["token"]
        profile = self.profile_id(token)
        target = self.make(token, profile, "Song", "2026-04-01", "spotify", 100)
        source = self.make(token, profile, "Song (Official Video)", "2026-04-02", "youtube", 50)
        result = self.client.post(f"/api/releases/{target}/merge", headers=self.auth(token),
                                  json={"source_release_ids": [source], "title": "Song"}).json()
        self.assertEqual((result["content_moved"], result["content_count"]), (1, 2))
        self.assertEqual(result["release"]["source"], "organized")
        self.assertEqual(self.sql("SELECT count(*) AS n FROM releases WHERE id = $1", source)[0]["n"], 0)
        self.assertEqual(self.sql("SELECT DISTINCT release_id FROM metric_snapshots WHERE profile_id = $1", profile),
                         [{"release_id": target}])

    def test_merge_with_a_foreign_release_changes_nothing(self):
        token = self.register("merge2@example.com")["token"]
        other = self.register("merge3@example.com")["token"]
        mine = self.make(token, self.profile_id(token), "A", "2026-04-01", "spotify", 1)
        theirs = self.make(other, self.profile_id(other), "B", "2026-04-01", "youtube", 1)
        response = self.client.post(f"/api/releases/{mine}/merge", headers=self.auth(token),
                                    json={"source_release_ids": [theirs]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM releases WHERE id = ANY($1)", [mine, theirs])[0]["n"], 2)

    def test_merge_rolls_back_when_a_step_fails(self):
        import routes
        token = self.register("merge4@example.com")["token"]
        profile = self.profile_id(token)
        target = self.make(token, profile, "T", "2026-04-01", "spotify", 1)
        source = self.make(token, profile, "S", "2026-04-01", "youtube", 1)
        real_delete = routes.db.delete

        async def failing_delete(table, where):
            raise RuntimeError("simulated failure")

        routes.db.delete = failing_delete
        try:
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/releases/{target}/merge", headers=self.auth(token),
                                 json={"source_release_ids": [source]})
        finally:
            routes.db.delete = real_delete
        moved = self.sql("SELECT release_id FROM content_items WHERE profile_id = $1 ORDER BY release_id", profile)
        self.assertEqual(sorted(r["release_id"] for r in moved), sorted([target, source]))
        self.assertIsNone(self.sql("SELECT source FROM releases WHERE id = $1", target)[0]["source"])

    def test_suggestions_and_dismissal(self):
        token = self.register("match@example.com")["token"]
        profile = self.profile_id(token)
        a = self.make(token, profile, "Neon Rain", "2026-04-01", "spotify", 1)
        b = self.make(token, profile, "Neon Rain (Official Video)", "2026-04-03", "youtube", 1)
        suggestions = self.client.get(f"/api/release-match-suggestions?profile_id={profile}",
                                      headers=self.auth(token)).json()["suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["suggested_target_id"], a)
        for _ in range(2):  # dismissing twice is fine
            r = self.client.post(f"/api/release-match-suggestions/dismiss?profile_id={profile}&release_a={a}&release_b={b}",
                                 headers=self.auth(token))
            self.assertEqual(r.status_code, 200)
        suggestions = self.client.get(f"/api/release-match-suggestions?profile_id={profile}",
                                      headers=self.auth(token)).json()["suggestions"]
        self.assertEqual(suggestions, [])


@requires_postgres
class ReportsAndDemo(ApiTestCase):
    def test_demo_seed_report_and_public_share(self):
        token = self.register("demo@example.com")["token"]
        profile = self.profile_id(token)
        h = self.auth(token)
        self.assertTrue(self.client.post("/api/demo/seed", headers=h).json()["seeded"])
        self.assertFalse(self.client.post("/api/demo/seed", headers=h).json()["seeded"])
        overview = self.client.get(f"/api/analytics/overview?profile_id={profile}", headers=h).json()
        self.assertEqual(overview["release_count"], 3)
        self.assertGreater(overview["totals"]["reach"], 0)

        async def fake_ask(prompt, schema=None):
            return '{"summary": "Grounded summary", "recommendations": ["one"]}'

        with patch("ai._ask", fake_ask):
            report = self.client.post("/api/reports", headers=h, json={"profile_id": profile, "title": "Q1"}).json()["report"]
        self.assertEqual(report["summary"], "Grounded summary")
        self.assertEqual(report["totals"], overview["totals"])
        listed = self.client.get(f"/api/reports?profile_id={profile}", headers=h).json()["reports"]
        self.assertEqual(listed[0]["platform_breakdown"], overview["platform_breakdown"])
        self.client.cookies.clear()
        shared = self.client.get(f"/api/reports/shared/{report['share_id']}").json()["report"]
        self.assertEqual(shared["title"], "Q1")
        self.assertEqual(set(shared), {"id", "title", "share_id", "totals", "platform_breakdown",
                                       "releases", "summary", "recommendations", "created_at"})
        self.assertRegex(report["share_id"], r"^[0-9a-f]{32}$")

    def test_ai_without_a_key_says_so(self):
        token = self.register("noai@example.com")["token"]
        profile = self.profile_id(token)
        self.client.post("/api/demo/seed", headers=self.auth(token))
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "AI_MODEL": ""}):
            response = self.client.post("/api/ai/ask", headers=self.auth(token),
                                        json={"profile_id": profile, "question": "How am I doing?"})
        self.assertEqual(response.status_code, 503)

    def test_ai_answers_with_follow_up_questions(self):
        import ai_provider
        token = self.register("claude@example.com")["token"]
        profile = self.profile_id(token)
        self.client.post("/api/demo/seed", headers=self.auth(token))
        prompts = []

        class FakeClaude:
            configured = True

            async def complete(self, system_prompt, user_message, schema=None):
                prompts.append((user_message, schema))
                if "refuse" in user_message:
                    raise ai_provider.AiRefused()
                return '{"answer": "Reach is up.", "follow_ups": ["Why?", "  ", "Which song?", "Where?", "When?"]}'

        with patch("ai.build_provider", FakeClaude):
            ask = lambda q: self.client.post("/api/ai/ask", headers=self.auth(token),
                                             json={"profile_id": profile, "question": q})
            body = ask("How am I doing?").json()
            refused = ask("please refuse")
        self.assertEqual((body["answer"], body["follow_ups"]), ("Reach is up.", ["Why?", "Which song?", "Where?"]))
        self.assertIn("FACTS", prompts[0][0])
        self.assertEqual(prompts[0][1]["required"], ["answer", "follow_ups"])
        self.assertEqual(refused.status_code, 422)

    def test_claude_is_configured_by_its_key(self):
        import ai_provider
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "AI_MODEL": ""}):
            self.assertFalse(ai_provider.build_provider().configured)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "AI_MODEL": ""}):
            provider = ai_provider.build_provider()
        self.assertEqual((provider.configured, provider._model), (True, "claude-opus-5"))


@requires_postgres
class PlatformSyncWrites(ApiTestCase):
    """The upserts YouTube, SoundCloud and history import rely on."""

    def test_youtube_video_upsert_is_idempotent(self):
        import youtube
        body = self.register("yt@example.com")
        profile = self.run_db(youtube._owned_profile, self.profile_id(body["token"]), body["user"]["user_id"])
        video = {"id": "vid123", "snippet": {"title": "Clip", "publishedAt": "2026-01-10T12:00:00Z"},
                 "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "1"}}
        first = self.run_db(youtube._upsert_video, profile, body["user"]["user_id"], "chan", video)
        video["statistics"]["viewCount"] = "25"
        second = self.run_db(youtube._upsert_video, profile, body["user"]["user_id"], "chan", video)
        self.assertEqual(first, (True, True))
        self.assertEqual(second, (False, False))
        snaps = self.sql("SELECT views, source, unavailable_metrics FROM metric_snapshots")
        self.assertEqual(snaps, [{"views": 25, "source": "youtube_api", "unavailable_metrics": ["shares", "followers"]}])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM content_items WHERE external_id = 'vid123'")[0]["n"], 1)

    def test_connection_upsert_keeps_one_row_per_platform(self):
        from database import db
        body = self.register("conn@example.com")
        profile = self.profile_id(body["token"])
        row = {"id": "conn_a", "profile_id": profile, "owner_id": body["user"]["user_id"], "platform": "soundcloud",
               "status": "connected", "scopes": "non-expiring", "connected_at": "2026-01-01T00:00:00+00:00"}
        self.run_db(db.upsert, "platform_connections", row, ("profile_id", "platform"), ("id",))
        self.run_db(db.upsert, "platform_connections", {**row, "id": "conn_b", "status": "needs_reconnect"},
                    ("profile_id", "platform"), ("id",))
        rows = self.sql("SELECT id, status, scopes FROM platform_connections")
        self.assertEqual(rows, [{"id": "conn_a", "status": "needs_reconnect", "scopes": ["non-expiring"]}])


class FakePlatform:
    """Stands in for httpx.AsyncClient: routes requests to canned platform answers."""

    routes = {}
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _answer(self, method, url, **kwargs):
        import httpx
        FakePlatform.calls.append((method, url, kwargs))
        for prefix, handler in FakePlatform.routes.items():
            if url.startswith(prefix):
                status, body = handler(kwargs)
                return httpx.Response(status, json=body, request=httpx.Request(method, url))
        raise AssertionError(f"unexpected request {method} {url}")

    async def get(self, url, **kwargs):
        return await self._answer("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._answer("POST", url, **kwargs)


@requires_postgres
class PlatformOAuthFlows(ApiTestCase):
    """Connect -> callback -> sync -> status -> disconnect, with the platforms faked."""

    def setUp(self):
        self.client.cookies.clear()
        FakePlatform.calls = []
        self.env = patch.dict("os.environ", {
            "YOUTUBE_CLIENT_ID": "yt-client", "YOUTUBE_CLIENT_SECRET": "yt-secret",
            "YOUTUBE_REDIRECT_URI": "https://api.example.com/api/youtube/callback",
            "SOUNDCLOUD_CLIENT_ID": "sc-client", "SOUNDCLOUD_CLIENT_SECRET": "sc-secret",
            "SOUNDCLOUD_REDIRECT_URI": "https://api.example.com/api/soundcloud/callback",
            "SOUNDCLOUD_TOKEN_ENCRYPTION_KEY": "another-long-random-secret",
        })
        self.env.start()
        self.http = patch("httpx.AsyncClient", FakePlatform)
        self.http.start()

    def tearDown(self):
        self.http.stop()
        self.env.stop()

    def connect(self, platform, token, profile):
        response = self.client.post(f"/api/{platform}/connect?profile_id={profile}", headers=self.auth(token))
        self.assertEqual(response.status_code, 200, response.text)
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(response.json()["auth_url"]).query)["state"][0]

    def callback(self, platform, state):
        response = self.client.get(f"/api/{platform}/callback", params={"code": "c", "state": state},
                                   follow_redirects=False)
        return response.headers["location"]

    def test_youtube(self):
        import youtube
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        FakePlatform.routes = {
            youtube.TOKEN_URL: lambda kw: (200, {
                "access_token": "yt-access", "refresh_token": "yt-refresh", "expires_in": 3600,
                "scope": f"{youtube.YOUTUBE_READ_SCOPE} {youtube.YOUTUBE_ANALYTICS_SCOPE}"}),
            f"{youtube.YOUTUBE_API}/channels": lambda kw: (200, {"items": [{
                "id": "chan1", "snippet": {"title": "Luna"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                "statistics": {"viewCount": "999", "subscriberCount": "50", "videoCount": "2"}}]}),
            f"{youtube.YOUTUBE_API}/playlistItems": lambda kw: (200, {"items": [
                {"contentDetails": {"videoId": "v1"}}, {"contentDetails": {"videoId": "v2"}}]}),
            f"{youtube.YOUTUBE_API}/videos": lambda kw: (200, {"items": [
                {"id": vid, "snippet": {"title": f"Video {vid}", "publishedAt": f"{yesterday}T08:00:00Z"},
                 "statistics": {"viewCount": "10", "likeCount": "1", "commentCount": "0"}} for vid in ("v1", "v2")]}),
            "https://youtubeanalytics.googleapis.com": lambda kw: (200, {
                "columnHeaders": [{"name": n} for n in ("day", "video", "views", "likes", "comments", "shares", "subscribersGained")],
                "rows": [[yesterday, "v1", 7, 1, 0, 0, 0], [yesterday, "v2", 3, 0, 0, 0, 0]]}),
            youtube.REVOKE_URL: lambda kw: (200, {}),
        }
        body = self.register("youtube-flow@example.com")
        token, profile = body["token"], self.profile_id(body["token"])
        state = self.connect("youtube", token, profile)
        location = self.callback("youtube", state)
        self.assertIn("youtube=connected", location)
        self.assertIn("imported=2", location)
        self.assertIn("error", self.callback("youtube", state))  # state is single-use

        conn = self.sql("SELECT * FROM platform_connections WHERE profile_id = $1", profile)[0]
        self.assertEqual(conn["status"], "connected")
        self.assertNotIn("yt-refresh", str(conn))  # stored encrypted
        self.assertEqual(conn["channel_statistics"]["subscriber_count"], 50)
        self.assertEqual(conn["history_backfill_status"], "complete")

        sources = self.sql("SELECT source, count(*) AS n FROM metric_snapshots WHERE profile_id = $1 "
                           "GROUP BY source ORDER BY source", profile)
        self.assertEqual(sources, [{"source": "youtube_analytics_history", "n": 2}, {"source": "youtube_api", "n": 2}])
        status = self.client.get(f"/api/youtube/status?profile_id={profile}", headers=self.auth(token)).json()
        self.assertEqual(status["connection"]["account_name"], "Luna")
        history = self.client.get(f"/api/youtube/history-status?profile_id={profile}", headers=self.auth(token)).json()
        self.assertEqual((history["scope_granted"], history["history_points_written"]), (True, 2))

        # A manual sync the same day updates rather than duplicates.
        sync = self.client.post(f"/api/youtube/sync?profile_id={profile}", headers=self.auth(token)).json()
        self.assertEqual((sync["content_imported"], sync["snapshots_created"]), (0, 0))

        self.client.delete(f"/api/youtube/disconnect?profile_id={profile}", headers=self.auth(token))
        conn = self.sql("SELECT status, access_token_enc, refresh_token_enc FROM platform_connections "
                        "WHERE profile_id = $1", profile)[0]
        self.assertEqual(conn, {"status": "needs_auth", "access_token_enc": None, "refresh_token_enc": None})

    def test_youtube_history_starts_at_day_zero(self):
        import sync
        import youtube
        today = date.today()
        published = today - timedelta(days=6)
        day = lambda n: (published + timedelta(days=n)).isoformat()
        analytics_rows = [
            # Pacific-time day before the UTC publish date: belongs to Day 0.
            [day(-1), "v1", 2, 0, 0, 0, 0],
            # Nothing reported for Days 0-2, then activity on Day 3.
            [day(3), "v1", 5, 1, 0, 0, 0],
        ]
        analytics_calls = []

        def analytics(kw):
            analytics_calls.append(kw["params"])
            return 200, {"columnHeaders": [{"name": n} for n in (
                "day", "video", "views", "likes", "comments", "shares", "subscribersGained")],
                "rows": analytics_rows}

        FakePlatform.routes = {
            youtube.TOKEN_URL: lambda kw: (200, {
                "access_token": "yt-access", "refresh_token": "yt-refresh", "expires_in": 3600,
                "scope": f"{youtube.YOUTUBE_READ_SCOPE} {youtube.YOUTUBE_ANALYTICS_SCOPE}"}),
            f"{youtube.YOUTUBE_API}/channels": lambda kw: (200, {"items": [{
                "id": "chan1", "snippet": {"title": "Luna"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}},
                "statistics": {"viewCount": "7", "subscriberCount": "5", "videoCount": "1"}}]}),
            f"{youtube.YOUTUBE_API}/playlistItems": lambda kw: (200, {"items": [{"contentDetails": {"videoId": "v1"}}]}),
            f"{youtube.YOUTUBE_API}/videos": lambda kw: (200, {"items": [
                {"id": "v1", "snippet": {"title": "Late starter", "publishedAt": f"{day(0)}T03:00:00Z"},
                 "statistics": {"viewCount": "7", "likeCount": "1", "commentCount": "0"}}]}),
            "https://youtubeanalytics.googleapis.com": analytics,
        }
        body = self.register("youtube-day-zero@example.com")
        token, profile = body["token"], self.profile_id(body["token"])
        self.callback("youtube", self.connect("youtube", token, profile))
        release = self.sql("SELECT release_id, id FROM content_items WHERE profile_id = $1", profile)[0]

        # A day an older import carried forward past what YouTube had reported.
        self.sql("INSERT INTO metric_snapshots (id, content_item_id, release_id, profile_id, date, views, reach, source) "
                 "VALUES ('stale', $1, $2, $3, $4, 7, 7, 'youtube_analytics_history')",
                 release["id"], release["release_id"], profile, date.fromisoformat(day(5)))
        imported = self.client.post(f"/api/youtube/backfill-history?profile_id={profile}", headers=self.auth(token))
        self.assertEqual(imported.status_code, 200, imported.text)

        history = self.sql("SELECT date, views FROM metric_snapshots WHERE profile_id = $1 "
                           "AND source = 'youtube_analytics_history' ORDER BY date", profile)
        self.assertEqual(history, [{"date": day(0), "views": 2}, {"date": day(1), "views": 2},
                                   {"date": day(2), "views": 2}, {"date": day(3), "views": 7}])
        race = self.client.get(f"/api/analytics/release-race?profile_id={profile}&release_ids={release['release_id']}"
                               f"&metric=views&max_day=3", headers=self.auth(token)).json()
        self.assertEqual([p["day"] for p in race["releases"][0]["series"]], [0, 1, 2, 3])

        # The daily sync re-imports history for recent releases.
        analytics_calls.clear()
        self.run_db(sync.sync_profile, profile)
        self.assertEqual(len(analytics_calls), 1)

    def test_soundcloud(self):
        import soundcloud
        FakePlatform.routes = {
            soundcloud.TOKEN_URL: lambda kw: (200, {"access_token": "sc-access", "refresh_token": "sc-refresh",
                                                    "expires_in": 3600, "scope": "non-expiring"}),
            f"{soundcloud.API_BASE}/me/tracks": lambda kw: (200, {"collection": [
                {"urn": "soundcloud:tracks:1", "title": "Track", "created_at": "2026-08-01T00:00:00Z",
                 "playback_count": 40, "favoritings_count": 2, "comment_count": 1, "reposts_count": 1}],
                "next_href": None}),
            f"{soundcloud.API_BASE}/me": lambda kw: (200, {"username": "luna", "urn": "soundcloud:users:9",
                                                           "followers_count": 12}),
            soundcloud.SIGN_OUT_URL: lambda kw: (200, {}),
        }
        body = self.register("soundcloud-flow@example.com")
        token, profile = body["token"], self.profile_id(body["token"])
        location = self.callback("soundcloud", self.connect("soundcloud", token, profile))
        self.assertIn("soundcloud=connected", location)
        conn = self.sql("SELECT status, scopes, account_statistics FROM platform_connections "
                        "WHERE profile_id = $1", profile)[0]
        self.assertEqual(conn["status"], "connected")
        self.assertEqual(conn["scopes"], ["non-expiring"])
        self.assertEqual(conn["account_statistics"]["followers_count"], 12)
        snap = self.sql("SELECT plays, engagement, source FROM metric_snapshots WHERE profile_id = $1", profile)
        self.assertEqual(snap, [{"plays": 40, "engagement": 4, "source": "soundcloud_api"}])

        # The profile sync finds the connection and refreshes it without duplicating the day.
        import sync
        result = self.run_db(sync.sync_profile, profile)
        self.assertEqual((result["connections_synced"], result["snapshots_created"]), (1, 0))

        self.client.delete(f"/api/soundcloud/disconnect?profile_id={profile}", headers=self.auth(token))
        self.assertEqual(self.sql("SELECT status FROM platform_connections WHERE profile_id = $1", profile),
                         [{"status": "needs_auth"}])


if __name__ == "__main__":
    unittest.main()
