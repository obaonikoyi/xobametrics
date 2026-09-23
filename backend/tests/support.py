"""
Shared set-up for tests that need a real PostgreSQL database.

Point TEST_DATABASE_URL at a server where the tests may create and drop a
database (default: postgres on localhost:5433, as CI starts it). Each test
class gets an empty database; nothing else on that server is touched.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse, urlunparse

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SERVER_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost:5433/postgres")
TEST_DB = "xobametrics_test"

os.environ["DATABASE_URL"] = urlunparse(urlparse(SERVER_URL)._replace(path=f"/{TEST_DB}"))
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256")
os.environ.setdefault("FRONTEND_URL", "https://app.example.com")
os.environ.setdefault("CORS_ORIGINS", "https://app.example.com")
os.environ.pop("ADMIN_PASSWORD", None)
os.environ.pop("MONGO_MIGRATION_URL", None)
os.environ.pop("BETA_INVITE_CODES", None)
os.environ["ENABLE_SCHEDULED_SYNC"] = "false"
os.environ["ENABLE_DEMO_SEED"] = "false"


def reset_database():
    """Drop and recreate the test database so each class starts empty."""
    import asyncpg

    async def run():
        conn = await asyncpg.connect(SERVER_URL)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        finally:
            await conn.close()

    asyncio.run(run())


def postgres_available() -> bool:
    import asyncpg

    async def probe():
        conn = await asyncpg.connect(SERVER_URL, timeout=3)
        await conn.close()

    try:
        asyncio.run(probe())
        return True
    except Exception:
        return False


requires_postgres = unittest.skipUnless(
    postgres_available(), f"PostgreSQL not reachable at {SERVER_URL}"
)


class ApiTestCase(unittest.TestCase):
    """Runs the real app (startup, schema, routes) against an empty database."""

    @classmethod
    def setUpClass(cls):
        reset_database()
        from fastapi.testclient import TestClient
        import server

        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def run_db(self, fn, *args):
        """Call an async function on the app's event loop (where the pool lives)."""
        return self.client.portal.call(fn, *args)

    def sql(self, query, *args):
        from database import db
        return self.run_db(db.fetch, query, *args)

    def register(self, email, password="Passw0rd!long", name="Artist", **extra):
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": name, **extra},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def profile_id(self, token):
        workspaces = self.client.get("/api/workspaces", headers=self.auth(token)).json()["workspaces"]
        return workspaces[0]["profiles"][0]["id"]
