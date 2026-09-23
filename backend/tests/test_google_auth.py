"""Google sign-in, end to end against a real PostgreSQL database and a fake Google.

No network or Google credentials: the token endpoint is stubbed and ID tokens
are signed with a throwaway RSA key standing in for Google's. Needs
TEST_DATABASE_URL (see support.py).

Execute with: python -m unittest discover -s backend/tests -p 'test_google_auth.py'
"""
import os
import time
import unittest
from urllib.parse import parse_qs, urlparse

os.environ["GOOGLE_CLIENT_ID"] = "client-123.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "https://api.example.com/api/auth/google/callback"
os.environ["FRONTEND_URL"] = "https://app.example.com"

from support import ApiTestCase, requires_postgres  # noqa: E402

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import google_auth  # noqa: E402

GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
BROWSER_KEY = "b" * 64


@requires_postgres
class GoogleSignIn(ApiTestCase):
    def setUp(self):
        # Each test starts from empty tables.
        self.sql("TRUNCATE users, oauth_states CASCADE")
        self.client.cookies.clear()
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

    def _states(self, type_="google_signin_state"):
        return self.sql("SELECT * FROM oauth_states WHERE type = $1", type_)

    def _users(self):
        return self.sql("SELECT * FROM users ORDER BY created_at")

    def _start(self, mode="signin", headers=None, invite_code=None):
        response = self.client.post(
            "/api/auth/google/start",
            json={"browser_key": BROWSER_KEY, "mode": mode, "invite_code": invite_code},
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
        saved = self._states()[0]
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
        self.assertEqual(len(self.sql("SELECT * FROM workspaces")), 1)
        self.assertEqual(len(self.sql("SELECT * FROM creator_profiles")), 1)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        self.assertEqual(me.json()["email"], "artist@example.com")

    def test_returning_user_is_found_by_google_id_even_if_email_changed(self):
        self._exchange(self._sign_in()["code"])
        self.claims["email"] = "renamed@example.com"
        body = self._exchange(self._sign_in()["code"]).json()
        self.assertEqual(body["user"]["email"], "artist@example.com")
        self.assertEqual(len(self._users()), 1)

    def test_code_verifier_is_sent_to_the_token_endpoint(self):
        query = self._start()
        verifier = self._states()[0]["code_verifier"]
        self._callback(query["state"][0], code="the-code")
        self.assertEqual(self.exchanged, [("the-code", verifier)])

    # --- the ID token is checked -------------------------------------------

    def test_token_signed_by_another_key_is_refused(self):
        self.signing_key = OTHER_KEY
        self.assertEqual(self._sign_in(), {"error": "invalid_id_token"})
        self.assertEqual(self._users(), [])

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
        self.sql("UPDATE oauth_states SET expires_at = '2000-01-01T00:00:00+00:00'")
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
        self.assertFalse(any(d["nonce"] == code for d in self.sql("SELECT nonce FROM oauth_states")))

    # --- accounts are never taken over by email -----------------------------

    def _register(self, email="artist@example.com"):
        response = self.client.post("/api/auth/register",
                                    json={"email": email, "password": "Passw0rd!long", "name": "Pw"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def test_password_account_with_same_email_is_not_taken_over(self):
        self._register()
        self.assertEqual(self._sign_in(), {"error": "password_account_exists"})
        self.assertIsNone(self._users()[0]["google_sub"])

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
        self.sql("INSERT INTO users (user_id, email, auth_provider) VALUES ('user_legacy', 'artist@example.com', 'google')")
        body = self._exchange(self._sign_in()["code"]).json()
        self.assertEqual(body["user"]["user_id"], "user_legacy")
        self.assertEqual(self._users()[0]["google_sub"], "google-sub-1")

    # --- invite-only beta -------------------------------------------------------

    def test_new_google_account_needs_an_invite_when_codes_are_set(self):
        os.environ["BETA_INVITE_CODES"] = "letmein"
        try:
            self.assertEqual(self._sign_in(), {"error": "invite_required"})
            self.assertEqual(self._users(), [])
            query = self._start(invite_code="letmein")
            body = self._exchange(self._callback(query["state"][0])["code"]).json()
            self.assertEqual(body["user"]["email"], "artist@example.com")
            # Existing accounts sign in without a code.
            again = self._exchange(self._sign_in()["code"])
            self.assertEqual(again.status_code, 200)
        finally:
            del os.environ["BETA_INVITE_CODES"]

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
