"""Google sign-in, end to end against an in-memory database and a fake Google.

No MongoDB, network or Google credentials: the token endpoint is stubbed and ID
tokens are signed with a throwaway RSA key standing in for Google's.

Execute with: python -m unittest discover -s backend/tests -p 'test_google_auth.py'
"""
import os
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("MONGO_URL", "mongodb://unused.invalid:27017")
os.environ.setdefault("DB_NAME", "unused")
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256"
os.environ["GOOGLE_CLIENT_ID"] = "client-123.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "https://api.example.com/api/auth/google/callback"
os.environ["FRONTEND_URL"] = "https://app.example.com"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

import auth  # noqa: E402
import google_auth  # noqa: E402

GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
BROWSER_KEY = "b" * 64


class FakeCollection:
    def __init__(self, unique=()):
        self.docs = []
        self.unique = unique

    @staticmethod
    def _matches(doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def _check_unique(self, candidate, ignore=None):
        for field in self.unique:
            value = candidate.get(field)
            if value is None:
                continue
            for doc in self.docs:
                if doc is not ignore and doc.get(field) == value:
                    raise DuplicateKeyError(f"duplicate {field}")

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc):
        self._check_unique(doc)
        self.docs.append(dict(doc))

    async def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                self._check_unique({**doc, **update["$set"]}, ignore=doc)
                doc.update(update["$set"])
                return

    async def find_one_and_delete(self, query):
        for doc in self.docs:
            if self._matches(doc, query):
                self.docs.remove(doc)
                return dict(doc)
        return None


class FakeDb:
    def __init__(self):
        self.users = FakeCollection(unique=("email", "google_sub"))
        self.oauth_states = FakeCollection(unique=("nonce",))
        self.workspaces = FakeCollection()
        self.creator_profiles = FakeCollection()


class GoogleSignIn(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        auth.db = self.db
        google_auth.db = self.db
        self.claims = {
            "sub": "google-sub-1",
            "email": "Artist@Example.com",
            "email_verified": True,
            "name": "Artist",
            "picture": "https://example.com/p.png",
        }
        self.signing_key = GOOGLE_KEY
        self.token_status = 200
        self.exchanged = []
        self.nonce_override = None

        async def fake_exchange(code, code_verifier):
            self.exchanged.append((code, code_verifier))
            if self.token_status >= 400:
                raise google_auth.SignInRefused("token_exchange_failed")
            return self._id_token()

        async def fake_signing_key(id_token):
            return GOOGLE_KEY.public_key()

        self._orig = (google_auth._exchange_code, google_auth._signing_key)
        google_auth._exchange_code = fake_exchange
        google_auth._signing_key = fake_signing_key

        app = FastAPI()
        app.include_router(auth.auth_router)
        app.include_router(google_auth.router)
        self.client = TestClient(app)

    def tearDown(self):
        google_auth._exchange_code, google_auth._signing_key = self._orig

    def _id_token(self, **overrides):
        now = int(time.time())
        payload = {
            "iss": "https://accounts.google.com",
            "aud": os.environ["GOOGLE_CLIENT_ID"],
            "iat": now,
            "exp": now + 3600,
            "nonce": self.nonce_override or self.current_nonce,
            **self.claims,
            **overrides,
        }
        return jwt.encode(payload, self.signing_key, algorithm="RS256")

    def _start(self, mode="signin", headers=None):
        response = self.client.post(
            "/api/auth/google/start",
            json={"browser_key": BROWSER_KEY, "mode": mode},
            headers=headers or {},
        )
        self.assertEqual(response.status_code, 200, response.text)
        query = parse_qs(urlparse(response.json()["auth_url"]).query)
        self.current_nonce = query["nonce"][0]
        return query

    def _callback(self, state, code="google-code"):
        response = self.client.get(
            "/api/auth/google/callback",
            params={"code": code, "state": state},
            follow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 307))
        location = urlparse(response.headers["location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}",
                         "https://app.example.com/auth/google")
        self.assertEqual(location.query, "")
        return {k: v[0] for k, v in parse_qs(location.fragment).items()}

    def _exchange(self, code, browser_key=BROWSER_KEY):
        return self.client.post(
            "/api/auth/google/exchange", json={"code": code, "browser_key": browser_key}
        )

    def _sign_in(self):
        query = self._start()
        return self._callback(query["state"][0])

    # --- the happy path -----------------------------------------------------

    def test_authorization_url_uses_pkce_and_openid_scopes(self):
        query = self._start()
        self.assertEqual(query["scope"], ["openid email profile"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], [os.environ["GOOGLE_REDIRECT_URI"]])
        saved = self.db.oauth_states.docs[0]
        self.assertEqual(query["code_challenge"], [google_auth._pkce_challenge(saved["code_verifier"])])
        self.assertNotEqual(saved["browser_key_hash"], BROWSER_KEY)

    def test_new_google_user_is_created_and_signed_in(self):
        landing = self._sign_in()
        response = self._exchange(landing["code"])
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["user"]["email"], "artist@example.com")
        self.assertTrue(body["user"]["google_linked"])
        self.assertEqual(body["user"]["auth_provider"], "google")
        self.assertEqual(len(self.db.workspaces.docs), 1)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        self.assertEqual(me.json()["email"], "artist@example.com")

    def test_returning_user_is_found_by_google_id_even_if_email_changed(self):
        self._exchange(self._sign_in()["code"])
        self.claims["email"] = "renamed@example.com"
        body = self._exchange(self._sign_in()["code"]).json()
        self.assertEqual(body["user"]["email"], "artist@example.com")
        self.assertEqual(len(self.db.users.docs), 1)

    def test_code_verifier_is_sent_to_the_token_endpoint(self):
        query = self._start()
        verifier = self.db.oauth_states.docs[0]["code_verifier"]
        self._callback(query["state"][0], code="the-code")
        self.assertEqual(self.exchanged, [("the-code", verifier)])

    # --- the ID token is checked -------------------------------------------

    def test_token_signed_by_another_key_is_refused(self):
        self.signing_key = OTHER_KEY
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})
        self.assertEqual(self.db.users.docs, [])

    def test_wrong_nonce_is_refused(self):
        self.nonce_override = "not-the-nonce"
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})

    def test_wrong_audience_is_refused(self):
        self.claims["aud"] = "someone-elses-client"
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})

    def test_wrong_issuer_is_refused(self):
        self.claims["iss"] = "https://evil.example.com"
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})

    def test_expired_token_is_refused(self):
        self.claims["exp"] = int(time.time()) - 3600
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})

    def test_unverified_email_is_refused(self):
        self.claims["email_verified"] = False
        self.assertEqual(self._sign_in(), {"error": "google_email_not_verified"})

    def test_failed_token_exchange_is_reported(self):
        self.token_status = 400
        self.assertEqual(self._sign_in(), {"error": "token_exchange_failed"})

    # --- state and one-time codes -------------------------------------------

    def test_unknown_state_is_refused(self):
        self.current_nonce = "x"
        self.assertEqual(self._callback("forged-state"), {"error": "sign_in_expired_or_already_used"})

    def test_state_cannot_be_replayed(self):
        state = self._start()["state"][0]
        self._callback(state)
        self.assertEqual(self._callback(state), {"error": "sign_in_expired_or_already_used"})

    def test_expired_state_is_refused(self):
        state = self._start()["state"][0]
        self.db.oauth_states.docs[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.assertEqual(self._callback(state), {"error": "sign_in_expired_or_already_used"})

    def test_google_denial_is_reported(self):
        response = self.client.get("/api/auth/google/callback", params={"error": "access_denied"},
                                   follow_redirects=False)
        self.assertTrue(response.headers["location"].endswith("#error=access_denied"))

    def test_login_code_requires_the_browser_that_started(self):
        code = self._sign_in()["code"]
        self.assertEqual(self._exchange(code, browser_key="a" * 64).status_code, 401)

    def test_login_code_is_single_use(self):
        code = self._sign_in()["code"]
        self.assertEqual(self._exchange(code).status_code, 200)
        self.assertEqual(self._exchange(code).status_code, 401)

    def test_login_code_is_stored_hashed(self):
        code = self._sign_in()["code"]
        self.assertFalse(any(d.get("nonce") == code for d in self.db.oauth_states.docs))

    # --- accounts are never taken over by email -----------------------------

    def _register(self, email="artist@example.com"):
        response = self.client.post("/api/auth/register",
                                    json={"email": email, "password": "Passw0rd!long", "name": "Pw"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def test_password_account_with_same_email_is_not_taken_over(self):
        self._register()
        self.assertEqual(self._sign_in(), {"error": "password_account_exists"})
        user = self.db.users.docs[0]
        self.assertNotIn("google_sub", user)

    def test_password_account_can_link_google_while_signed_in(self):
        token = self._register()
        query = self._start(mode="link", headers={"Authorization": f"Bearer {token}"})
        landing = self._callback(query["state"][0])
        body = self._exchange(landing["code"]).json()
        self.assertEqual(body["mode"], "link")
        self.assertTrue(body["user"]["google_linked"])
        self.assertEqual(body["user"]["auth_provider"], "password")
        # ...after which Google sign-in reaches the same account.
        again = self._exchange(self._sign_in()["code"]).json()
        self.assertEqual(again["user"]["user_id"], body["user"]["user_id"])

    def test_linking_requires_being_signed_in(self):
        response = self.client.post("/api/auth/google/start",
                                    json={"browser_key": BROWSER_KEY, "mode": "link"})
        self.assertEqual(response.status_code, 401)

    def test_google_account_cannot_be_linked_to_two_users(self):
        self._exchange(self._sign_in()["code"])
        token = self._register(email="second@example.com")
        query = self._start(mode="link", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(self._callback(query["state"][0]),
                         {"error": "google_account_used_by_another_user"})

    def test_passwordless_legacy_google_account_is_linked(self):
        self.db.users.docs.append({"user_id": "user_legacy", "email": "artist@example.com",
                                   "auth_provider": "google", "role": "user"})
        body = self._exchange(self._sign_in()["code"]).json()
        self.assertEqual(body["user"]["user_id"], "user_legacy")
        self.assertEqual(self.db.users.docs[0]["google_sub"], "google-sub-1")

    # --- configuration --------------------------------------------------------

    def test_status_and_start_when_not_configured(self):
        saved = os.environ.pop("GOOGLE_CLIENT_SECRET")
        try:
            self.assertEqual(self.client.get("/api/auth/google/status").json(), {"configured": False})
            response = self.client.post("/api/auth/google/start", json={"browser_key": BROWSER_KEY})
            self.assertEqual(response.status_code, 503)
        finally:
            os.environ["GOOGLE_CLIENT_SECRET"] = saved


if __name__ == "__main__":
    unittest.main()
