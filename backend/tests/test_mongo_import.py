"""The one-time MongoDB -> PostgreSQL import, on data as messy as Mongo allows.

Execute with: python -m unittest discover -s backend/tests -p 'test_mongo_import.py'
(needs TEST_DATABASE_URL, see support.py).
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from support import ApiTestCase, requires_postgres


def mongo_documents():
    oid = object()  # stands in for a Mongo ObjectId; must never reach Postgres
    return {
        "users": [
            {"_id": oid, "user_id": "user_1", "email": "Artist@Example.com", "name": "Artist",
             "password_hash": "$2b$12$abc", "role": "admin", "auth_provider": "password",
             "beta_approved": True, "created_at": "2026-09-13T09:00:00+00:00", "legacy_flag": 1},
            {"_id": oid, "user_id": "user_g", "email": "g@example.com", "auth_provider": "google",
             "picture": "https://p", "created_at": datetime(2026, 9, 13, tzinfo=timezone.utc), "role": None},
            {"_id": oid, "user_id": "user_dup", "email": "artist@example.com"},
        ],
        "workspaces": [
            {"_id": oid, "id": "ws_1", "owner_id": "user_1", "name": "Artist", "type": "solo"},
            {"_id": oid, "id": "ws_orphan", "owner_id": "user_gone", "name": "x"},
        ],
        "creator_profiles": [
            {"_id": oid, "id": "prof_1", "workspace_id": "ws_1", "owner_id": "user_1", "name": "Artist"},
        ],
        "platform_connections": [
            {"_id": oid, "id": "conn_old", "profile_id": "prof_1", "workspace_id": "ws_1", "owner_id": "user_1",
             "platform": "youtube", "status": "needs_auth", "connected_at": "2026-09-01T00:00:00+00:00"},
            {"_id": oid, "id": "conn_live", "profile_id": "prof_1", "workspace_id": "ws_1", "owner_id": "user_1",
             "platform": "youtube", "status": "connected", "scopes": ["a", "b"],
             "channel_statistics": {"view_count": 10}, "connected_at": "2026-09-10T00:00:00+00:00",
             "access_token_enc": "enc", "access_token": "legacy plaintext field"},
        ],
        "releases": [
            {"_id": oid, "id": "rel_1", "profile_id": "prof_1", "workspace_id": "ws_1", "owner_id": "user_1",
             "title": "Song", "release_date": "2026-09-01", "cover": "#fff", "source": "youtube",
             "source_external_id": "vid"},
            {"_id": oid, "id": "rel_nodate", "profile_id": "prof_1", "owner_id": "user_1", "title": "No date"},
        ],
        "content_items": [
            {"_id": oid, "id": "ci_1", "release_id": "rel_1", "profile_id": "prof_1", "workspace_id": "ws_1",
             "owner_id": "user_1", "title": "Song", "platform": "youtube", "external_id": "vid",
             "published_at": "2026-09-01T10:00:00Z"},
            {"_id": oid, "id": "ci_dup", "release_id": "rel_1", "profile_id": "prof_1", "workspace_id": "ws_1",
             "owner_id": "user_1", "title": "Song again", "platform": "youtube", "external_id": "vid",
             "published_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
            {"_id": oid, "id": "ci_csv", "release_id": "rel_1", "profile_id": "prof_1", "owner_id": "user_1",
             "title": "CSV", "platform": "spotify", "external_id": None},
            {"_id": oid, "id": "ci_lost", "release_id": "rel_nodate", "profile_id": "prof_1",
             "owner_id": "user_1", "title": "Lost", "platform": "spotify"},
        ],
        "metric_snapshots": [
            {"_id": oid, "id": "s1", "content_item_id": "ci_1", "release_id": "rel_1", "profile_id": "prof_1",
             "date": "2026-09-02", "views": 10.0, "reach": 10, "source": "youtube_api"},
            # On the duplicate item: moves to ci_1, same day and source -> one row, the later one.
            {"_id": oid, "id": "s2", "content_item_id": "ci_dup", "release_id": "rel_1", "profile_id": "prof_1",
             "date": "2026-09-02", "views": 12, "reach": 12, "source": "youtube_api"},
            {"_id": oid, "id": "s3", "content_item_id": "ci_csv", "release_id": "rel_1", "profile_id": "prof_1",
             "date": "09/03/2026", "plays": 5},
            {"_id": oid, "id": "s4", "content_item_id": "ci_csv", "release_id": "rel_1", "profile_id": "prof_1",
             "date": "2026-09-03", "plays": 7, "day_offset": 2},
            {"_id": oid, "id": "s5", "content_item_id": "ci_lost", "release_id": "rel_nodate",
             "profile_id": "prof_1", "date": "2026-09-03", "plays": 1},
        ],
        "release_match_dismissals": [
            {"_id": oid, "owner_id": "user_1", "profile_id": "prof_1", "match_key": "rel_1::rel_x",
             "dismissed_at": "2026-09-05T00:00:00+00:00"},
        ],
        "reports": [
            {"_id": oid, "id": "rep_1", "profile_id": "prof_1", "owner_id": "user_1", "title": "Q3",
             "share_id": "share123", "totals": {"reach": 10}, "platform_breakdown": [],
             "releases": [{"id": "rel_1"}], "recommendations": ["x"], "summary": "ok"},
        ],
        "files": [
            {"_id": oid, "id": "file_1", "owner_id": "user_1", "profile_id": "prof_gone",
             "storage_path": None, "original_filename": "a.csv", "is_deleted": False},
        ],
    }


@requires_postgres
class MongoImport(ApiTestCase):
    def setUp(self):
        self.sql("TRUNCATE users CASCADE")

    def run_import(self):
        import mongo_import
        return self.run_db(mongo_import.import_documents, mongo_documents())

    def test_import_copies_and_cleans(self):
        summary = self.run_import()
        self.assertEqual(summary["copied"]["users"], 2)
        users = {u["user_id"]: u for u in self.sql("SELECT * FROM users")}
        self.assertEqual(users["user_1"]["email"], "artist@example.com")
        self.assertEqual(users["user_1"]["role"], "admin")
        self.assertEqual(users["user_g"]["role"], "user")  # None fell back to the default
        self.assertEqual(self.sql("SELECT id FROM workspaces"), [{"id": "ws_1"}])

        conns = self.sql("SELECT id, status, scopes, channel_statistics FROM platform_connections")
        self.assertEqual(conns, [{"id": "conn_live", "status": "connected", "scopes": ["a", "b"],
                                  "channel_statistics": {"view_count": 10}}])

        self.assertEqual([r["id"] for r in self.sql("SELECT id FROM releases")], ["rel_1"])
        items = {r["id"]: r for r in self.sql("SELECT * FROM content_items")}
        self.assertEqual(sorted(items), ["ci_1", "ci_csv"])
        self.assertEqual(items["ci_1"]["published_at"], "2026-09-01T10:00:00Z")

        snaps = self.sql("SELECT id, content_item_id, date, views, plays, source FROM metric_snapshots ORDER BY id")
        self.assertEqual(snaps, [
            {"id": "s2", "content_item_id": "ci_1", "date": "2026-09-02", "views": 12, "plays": 0, "source": "youtube_api"},
            {"id": "s4", "content_item_id": "ci_csv", "date": "2026-09-03", "views": 0, "plays": 7, "source": "manual"},
        ])
        self.assertEqual(self.sql("SELECT release_ids FROM release_match_dismissals"),
                         [{"release_ids": ["rel_1", "rel_x"]}])
        report = self.sql("SELECT totals, releases FROM reports")[0]
        self.assertEqual(report, {"totals": {"reach": 10}, "releases": [{"id": "rel_1"}]})
        self.assertEqual(self.sql("SELECT profile_id FROM files"), [{"profile_id": None}])

        notes = summary["adjustments"]
        self.assertEqual(notes["users: duplicate email"], 1)
        self.assertEqual(notes["platform_connections: duplicate platform on a profile"], 1)
        self.assertEqual(notes["content_items: duplicate platform import folded together"], 1)
        self.assertEqual(notes["metric_snapshots: unreadable date"], 1)
        self.assertEqual(notes["platform_connections: dropped field access_token"], 1)

    def test_imported_accounts_work(self):
        self.run_import()
        # The imported password account can sign in once it has a known hash.
        from auth import hash_password
        self.sql("UPDATE users SET password_hash = $1 WHERE user_id = 'user_1'", hash_password("Passw0rd!long"))
        login = self.client.post("/api/auth/login", json={"email": "artist@example.com", "password": "Passw0rd!long"})
        self.assertEqual(login.status_code, 200)
        detail = self.client.get("/api/releases/rel_1", headers=self.auth(login.json()["token"])).json()
        self.assertEqual(detail["rollup"]["totals"]["views"], 12)
        self.assertEqual(detail["rollup"]["totals"]["plays"], 7)

    def test_import_is_all_or_nothing(self):
        import mongo_import
        from database import db
        docs = mongo_documents()
        real = db.insert_many

        async def fail_on_reports(table, rows):
            if table == "reports":
                raise RuntimeError("simulated failure")
            await real(table, rows)

        with patch.object(db, "insert_many", fail_on_reports):
            with self.assertRaises(RuntimeError):
                self.run_db(mongo_import.import_documents, docs)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM users")[0]["n"], 0)

    def test_never_imports_over_existing_data(self):
        import mongo_import
        self.register("already@example.com")
        with patch("mongo_import.load_from_mongo", side_effect=AssertionError("must not read Mongo")):
            self.assertIsNone(self.run_db(mongo_import.import_from_mongo_if_empty, "mongodb://x", "db"))

    def test_imports_into_an_empty_database(self):
        import mongo_import
        with patch("mongo_import.load_from_mongo", return_value=mongo_documents()):
            summary = self.run_db(mongo_import.import_from_mongo_if_empty, "mongodb://x", "db")
        self.assertEqual(summary["copied"]["releases"], 1)


if __name__ == "__main__":
    unittest.main()
