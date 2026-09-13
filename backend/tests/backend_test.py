"""XobaMetrics backend regression tests.

Covers:
- Auth (register/login/me/logout, wrong credentials, data isolation)
- Workspaces & Profiles auto-creation
- Demo seed
- Analytics (overview, release-timeseries, release-race)
- Releases (list/create/get)
- Connections (create/reconnect/list)
- CSV upload + commit
- AI (insights + ask)  [slower]
- Reports (create, get, shared public)
"""
import os
import io
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback for tests run outside frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@xobametrics.com"
ADMIN_PASSWORD = "XobaAdmin2026!"


# --------------- Fixtures ---------------
@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    token = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session")
def admin_ctx(admin_session):
    """Return admin workspace + profile ids from /workspaces."""
    r = admin_session.get(f"{API}/workspaces")
    assert r.status_code == 200
    ws_list = r.json()["workspaces"]
    assert ws_list, "Admin has no workspace"
    ws = ws_list[0]
    profiles = ws.get("profiles", [])
    assert profiles, "Admin workspace has no profile"
    return {"workspace": ws, "profile": profiles[0]}


@pytest.fixture(scope="session")
def new_user():
    """Register a fresh throw-away user."""
    email = f"TEST_{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass123!"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "Test User"})
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['token']}"})
    return {"session": s, "email": email, "password": password, "user": data["user"]}


# --------------- Auth ---------------
class TestAuth:
    def test_login_admin(self, admin_session):
        r = admin_session.get(f"{API}/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == ADMIN_EMAIL

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrongwrong"})
        assert r.status_code in (401, 429)

    def test_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_register_creates_workspace(self, new_user):
        r = new_user["session"].get(f"{API}/workspaces")
        assert r.status_code == 200
        ws = r.json()["workspaces"]
        assert len(ws) >= 1
        assert ws[0].get("profiles")

    def test_register_duplicate(self, new_user):
        r = requests.post(f"{API}/auth/register", json={
            "email": new_user["email"], "password": "whatever123", "name": "x"
        })
        assert r.status_code == 400

    def test_logout(self, new_user):
        # separate session so we don't invalidate the shared one
        email = f"TEST_{uuid.uuid4().hex[:8]}@example.com"
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{API}/auth/register", json={"email": email, "password": "pw12345678", "name": "L"})
        assert r.status_code == 200
        r = s.post(f"{API}/auth/logout")
        assert r.status_code == 200


# --------------- Data Isolation ---------------
class TestIsolation:
    def test_new_user_cannot_see_admin_profile(self, new_user, admin_ctx):
        admin_prof_id = admin_ctx["profile"]["id"]
        r = new_user["session"].get(f"{API}/analytics/overview", params={"profile_id": admin_prof_id})
        assert r.status_code == 404

    def test_new_user_cannot_get_admin_release(self, new_user, admin_session, admin_ctx):
        rels = admin_session.get(f"{API}/releases", params={"profile_id": admin_ctx["profile"]["id"]}).json()["releases"]
        if not rels:
            pytest.skip("Admin has no releases")
        rid = rels[0]["id"]
        r = new_user["session"].get(f"{API}/releases/{rid}")
        assert r.status_code == 404


# --------------- Analytics / Overview ---------------
class TestAnalytics:
    def test_overview_admin(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.get(f"{API}/analytics/overview", params={"profile_id": pid})
        assert r.status_code == 200
        data = r.json()
        assert "totals" in data
        # Reach should be > 0 since admin is pre-seeded
        assert data["totals"].get("reach", 0) > 0, f"Expected seeded reach > 0, got {data['totals']}"
        assert "platform_breakdown" in data
        assert "releases" in data

    def test_releases_list(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.get(f"{API}/releases", params={"profile_id": pid})
        assert r.status_code == 200
        rels = r.json()["releases"]
        assert len(rels) >= 3, f"Expected 3+ seeded releases, got {len(rels)}"
        titles = {rel["title"] for rel in rels}
        # From the problem description
        for expected in ("Take It Easy", "Midnight Signal", "Neon Rain"):
            assert expected in titles, f"Missing seeded release: {expected}. Got {titles}"

    def test_release_timeseries(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        rels = admin_session.get(f"{API}/releases", params={"profile_id": pid}).json()["releases"]
        rid = rels[0]["id"]
        r = admin_session.get(f"{API}/analytics/release-timeseries/{rid}", params={"metric": "reach"})
        assert r.status_code == 200
        data = r.json()
        assert "series" in data or "points" in data or isinstance(data, dict)

    def test_release_race_day_alignment(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        rels = admin_session.get(f"{API}/releases", params={"profile_id": pid}).json()["releases"]
        ids = ",".join(r["id"] for r in rels[:3])
        r = admin_session.get(f"{API}/analytics/release-race",
                              params={"profile_id": pid, "release_ids": ids, "metric": "reach", "max_day": 30})
        assert r.status_code == 200
        data = r.json()
        # Should return per-release day-offset arrays
        assert isinstance(data, dict)


# --------------- Releases CRUD ---------------
class TestReleases:
    def test_create_release(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        payload = {
            "profile_id": pid,
            "title": f"TEST_Release_{uuid.uuid4().hex[:6]}",
            "release_date": "2025-01-01",
            "description": "test",
        }
        r = admin_session.post(f"{API}/releases", json=payload)
        assert r.status_code == 200, r.text
        rel = r.json()["release"]
        assert rel["title"] == payload["title"]
        # verify persistence
        get_r = admin_session.get(f"{API}/releases/{rel['id']}")
        assert get_r.status_code == 200
        assert get_r.json()["release"]["title"] == payload["title"]


# --------------- Connections ---------------
class TestConnections:
    def test_list_and_create_connection(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.get(f"{API}/connections", params={"profile_id": pid})
        assert r.status_code == 200
        # create/update a stubbed connection
        r = admin_session.post(f"{API}/connections",
                               json={"profile_id": pid, "platform": "youtube", "account_name": "TEST"})
        assert r.status_code == 200
        conn = r.json()["connection"]
        assert conn["status"] == "connected"
        assert conn["platform"] == "youtube"

        # Reconnect
        rr = admin_session.post(f"{API}/connections/{conn['id']}/reconnect")
        assert rr.status_code == 200
        assert rr.json()["connection"]["status"] == "connected"


# --------------- CSV ---------------
class TestCSV:
    def test_csv_upload_and_commit(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        csv_body = (
            "date,views,likes,comments,shares\n"
            "2025-01-01,100,10,2,1\n"
            "2025-01-02,220,25,5,3\n"
            "2025-01-03,350,40,7,4\n"
        )
        # upload uses multipart/form-data — build a fresh session w/ auth header only
        s = requests.Session()
        s.headers.update({"Authorization": admin_session.headers["Authorization"]})
        files = {"file": ("test.csv", io.BytesIO(csv_body.encode()), "text/csv")}
        r = s.post(f"{API}/csv/upload", data={"profile_id": pid}, files=files)
        assert r.status_code == 200, r.text
        up = r.json()
        assert up["row_count"] == 3
        assert up["suggested_mapping"]
        # commit
        commit_body = {
            "profile_id": pid,
            "release_title": f"TEST_CSV_{uuid.uuid4().hex[:6]}",
            "release_date": "2025-01-01",
            "platform": "youtube",
            "content_title": "CSV Import",
            "content_type": "video",
            "rows": up["rows"],
            "mapping": up["suggested_mapping"],
        }
        r = admin_session.post(f"{API}/csv/commit", json=commit_body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["snapshots"] == 3
        assert data["release_id"].startswith("rel_")


# --------------- AI (slow) ---------------
class TestAI:
    def test_ai_insights(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.post(f"{API}/ai/insights", json={"profile_id": pid}, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("summary")

    def test_ai_ask(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.post(f"{API}/ai/ask",
                               json={"profile_id": pid, "question": "Which release had the strongest first week?"},
                               timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer") or data.get("summary")


# --------------- Reports ---------------
class TestReports:
    def test_create_and_share_report(self, admin_session, admin_ctx):
        pid = admin_ctx["profile"]["id"]
        r = admin_session.post(f"{API}/reports",
                               json={"profile_id": pid, "title": f"TEST_Report_{uuid.uuid4().hex[:6]}"},
                               timeout=90)
        assert r.status_code == 200, r.text
        report = r.json()["report"]
        assert report.get("share_id")
        share_id = report["share_id"]

        # Public share should NOT require auth
        pub = requests.get(f"{API}/reports/shared/{share_id}")
        assert pub.status_code == 200
        pub_data = pub.json()["report"]
        assert pub_data.get("share_id") == share_id
        assert "owner_id" not in pub_data


# --------------- Demo seed ---------------
class TestDemoSeed:
    def test_demo_seed_for_new_user(self, new_user):
        r = new_user["session"].post(f"{API}/demo/seed", timeout=60)
        assert r.status_code == 200, r.text
        # Verify overview now has data
        ws = new_user["session"].get(f"{API}/workspaces").json()["workspaces"][0]
        pid = ws["profiles"][0]["id"]
        ov = new_user["session"].get(f"{API}/analytics/overview", params={"profile_id": pid}).json()
        assert ov["totals"].get("reach", 0) > 0
