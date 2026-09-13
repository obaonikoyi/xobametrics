"""Security hardening verification tests (iteration 3)."""
import os
import io
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@xobametrics.com"
ADMIN_PASSWORD = "XobaAdmin2026!"

XRW = {"X-Requested-With": "XobaMetrics"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_ctx(admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    ws = requests.get(f"{API}/workspaces", headers=h).json()["workspaces"][0]
    profile_id = ws["profiles"][0]["id"]
    return {"token": admin_token, "headers": h, "profile_id": profile_id}


# ---------- Admin login (security seed) ----------
def test_admin_login_still_works(admin_token):
    assert admin_token and isinstance(admin_token, str)


# ---------- CSV upload CSRF header ----------
def _make_csv_bytes(rows=5):
    lines = ["date,streams"]
    for i in range(rows):
        lines.append(f"2025-01-{(i%28)+1:02d},{100+i}")
    return ("\n".join(lines)).encode()


def test_csv_upload_without_xrw_returns_403(admin_ctx):
    files = {"file": ("test.csv", _make_csv_bytes(), "text/csv")}
    data = {"profile_id": admin_ctx["profile_id"]}
    # Auth but NO X-Requested-With
    r = requests.post(f"{API}/csv/upload", headers=admin_ctx["headers"], files=files, data=data)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


def test_csv_upload_with_xrw_ok(admin_ctx):
    files = {"file": ("test.csv", _make_csv_bytes(), "text/csv")}
    data = {"profile_id": admin_ctx["profile_id"]}
    h = {**admin_ctx["headers"], **XRW}
    r = requests.post(f"{API}/csv/upload", headers=h, files=files, data=data)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert "headers" in body and "rows" in body


def test_csv_upload_non_csv_extension_returns_400(admin_ctx):
    files = {"file": ("evil.txt", b"date,streams\n2025-01-01,1", "text/plain")}
    data = {"profile_id": admin_ctx["profile_id"]}
    h = {**admin_ctx["headers"], **XRW}
    r = requests.post(f"{API}/csv/upload", headers=h, files=files, data=data)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_csv_upload_over_5mb_returns_413(admin_ctx):
    big = b"date,streams\n" + (b"2025-01-01,1\n" * 500000)  # ~6.5MB
    assert len(big) > 5 * 1024 * 1024
    files = {"file": ("big.csv", big, "text/csv")}
    data = {"profile_id": admin_ctx["profile_id"]}
    h = {**admin_ctx["headers"], **XRW}
    r = requests.post(f"{API}/csv/upload", headers=h, files=files, data=data)
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text}"


# ---------- CSV commit row cap ----------
def test_csv_commit_over_5000_rows_returns_413(admin_ctx):
    rows = [{"date": "2025-01-01", "streams": "1"} for _ in range(5001)]
    body = {
        "profile_id": admin_ctx["profile_id"],
        "platform": "spotify",
        "release_title": "TEST_toomany",
        "release_date": "2025-01-01",
        "mapping": {"date": "date", "plays": "streams"},
        "rows": rows,
    }
    h = {**admin_ctx["headers"], **XRW, "Content-Type": "application/json"}
    r = requests.post(f"{API}/csv/commit", headers=h, json=body)
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text}"


def test_csv_commit_small_ok_and_cleanup(admin_ctx):
    rows = [{"date": f"2025-01-{(i%28)+1:02d}", "streams": str(10+i)} for i in range(10)]
    body = {
        "profile_id": admin_ctx["profile_id"],
        "platform": "spotify",
        "release_title": "TEST_small_import",
        "release_date": "2025-01-01",
        "mapping": {"date": "date", "plays": "streams"},
        "rows": rows,
    }
    h = {**admin_ctx["headers"], **XRW, "Content-Type": "application/json"}
    r = requests.post(f"{API}/csv/commit", headers=h, json=body)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    rel_id = r.json()["release_id"]
    assert rel_id
    # Cleanup — delete via mongo directly since there's no delete endpoint
    # We track it for the summary; actual cleanup is at module teardown
    admin_ctx.setdefault("cleanup_release_ids", []).append(rel_id)


# ---------- Shared report ----------
@pytest.fixture(scope="module")
def created_report(admin_ctx):
    h = {**admin_ctx["headers"], **XRW, "Content-Type": "application/json"}
    body = {"profile_id": admin_ctx["profile_id"], "title": "TEST_security_report"}
    r = requests.post(f"{API}/reports", headers=h, json=body)
    assert r.status_code == 200, f"report create failed: {r.status_code} {r.text}"
    rep = r.json()["report"]
    admin_ctx.setdefault("cleanup_report_ids", []).append(rep["id"])
    return rep


def test_share_id_is_32_char_hex(created_report):
    sid = created_report["share_id"]
    assert len(sid) == 32, f"expected 32 chars, got {len(sid)}: {sid}"
    int(sid, 16)  # must be hex


def test_shared_report_no_auth_whitelisted_only(created_report):
    sid = created_report["share_id"]
    # No Authorization header at all
    r = requests.get(f"{API}/reports/shared/{sid}")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    rep = r.json()["report"]
    allowed = {"id", "title", "share_id", "totals", "platform_breakdown",
               "releases", "summary", "recommendations", "created_at"}
    extra = set(rep.keys()) - allowed
    assert not extra, f"leaked fields: {extra}"
    assert "owner_id" not in rep
    assert "profile_id" not in rep


# ---------- Data isolation regression ----------
def test_second_user_cannot_see_admin_data():
    import uuid as _u
    email = f"TEST_iso_{_u.uuid4().hex[:8]}@test.com"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "TestPass123!", "name": "Iso Test"})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    ws = requests.get(f"{API}/workspaces", headers=h).json()["workspaces"]
    assert len(ws) >= 1
    prof = ws[0]["profiles"][0]
    # This user should have no releases
    rels = requests.get(f"{API}/releases", headers=h, params={"profile_id": prof["id"]}).json()["releases"]
    assert rels == [], f"new user unexpectedly sees releases: {rels}"


# ---------- Module-level cleanup ----------
def test_zzz_cleanup(admin_ctx):
    """Cleanup TEST_ data created during tests via direct Mongo (no delete endpoints)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        pytest.skip("MONGO_URL/DB_NAME not available for cleanup")

    async def _cleanup():
        c = AsyncIOMotorClient(mongo_url)
        d = c[db_name]
        # Delete TEST_ reports
        await d.reports.delete_many({"title": {"$regex": "^TEST_"}})
        # Delete releases with TEST_ titles + their content + snapshots
        rels = await d.releases.find({"title": {"$regex": "^TEST_"}}, {"id": 1, "_id": 0}).to_list(1000)
        rel_ids = [r["id"] for r in rels]
        if rel_ids:
            content = await d.content_items.find({"release_id": {"$in": rel_ids}}, {"id": 1}).to_list(1000)
            cids = [c["id"] for c in content]
            await d.metric_snapshots.delete_many({"release_id": {"$in": rel_ids}})
            if cids:
                await d.content_items.delete_many({"id": {"$in": cids}})
            await d.releases.delete_many({"id": {"$in": rel_ids}})
        # Also clean up prior "spotify_test" release from iteration 2
        prev = await d.releases.find({"title": "spotify_test"}, {"id": 1, "_id": 0}).to_list(100)
        prev_ids = [r["id"] for r in prev]
        if prev_ids:
            cprev = await d.content_items.find({"release_id": {"$in": prev_ids}}, {"id": 1}).to_list(1000)
            cids2 = [c["id"] for c in cprev]
            await d.metric_snapshots.delete_many({"release_id": {"$in": prev_ids}})
            if cids2:
                await d.content_items.delete_many({"id": {"$in": cids2}})
            await d.releases.delete_many({"id": {"$in": prev_ids}})
        # Clean test users
        await d.users.delete_many({"email": {"$regex": "^TEST_iso_"}})
        c.close()

    asyncio.run(_cleanup())
