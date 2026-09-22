"""
Sign in with Google: OpenID Connect authorization code flow with PKCE.

Google proves who the person is; XobaMetrics then issues its own access token,
exactly as a password login does, so the rest of the app is unchanged.

What is checked, and why:

- The ID token's signature against Google's published keys, and its issuer,
  audience, expiry and nonce. Nothing about the user is taken from anywhere
  else.
- Google must say the email is verified.
- The flow is bound to the browser tab that started it. The frontend makes a
  random browser key, keeps it in sessionStorage and sends it to /start; the
  one-time login code the callback returns is only redeemable with that key.
  Without this, someone could start a sign-in as themselves and trick another
  person's browser into finishing it (login CSRF).
- A Google identity never takes over an existing password account by email.
  Registration does not verify email, so anyone could have registered someone
  else's address with a password first and kept that password after the real
  owner signed in with Google. To use Google with a password account, sign in
  with the password and link Google from the account menu (mode "link").

Accounts matched by email with no password and no Google id -- those created by
the builder's old delegated sign-in -- are linked on first sign-in, since there
is no second credential to worry about.
"""
import asyncio
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Literal
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from auth import (
    _ensure_workspace, _public_user, _set_cookie, create_access_token, get_current_user,
)
from database import db
from models import new_id, now_iso

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
SCOPE = "openid email profile"
STATE_TYPE = "google_signin_state"
CODE_TYPE = "google_signin_code"
STATE_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=2)


class StartRequest(BaseModel):
    browser_key: str = Field(min_length=32, max_length=256)
    mode: Literal["signin", "link"] = "signin"


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=256)
    browser_key: str = Field(min_length=32, max_length=256)


class SignInRefused(Exception):
    """A reason the callback sends back to the frontend instead of a login code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "https://metrics.3xoba.com").strip().rstrip("/")


def _redirect_uri() -> str:
    explicit = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    public_api = os.environ.get("PUBLIC_API_URL", "").strip().rstrip("/")
    if not public_api:
        return ""
    return f"{public_api}/api/auth/google/callback"


def _configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
        and _redirect_uri()
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _expired(expires_at: str) -> bool:
    try:
        moment = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < datetime.now(timezone.utc)


def _landing(**fragment: str) -> RedirectResponse:
    # A fragment is never sent to a server, so the one-time code stays out of
    # request logs on the way back to the frontend.
    return RedirectResponse(f"{_frontend_url()}/auth/google#{urlencode(fragment)}")


_jwks_client: jwt.PyJWKClient | None = None


async def _signing_key(id_token: str):
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    signing_key = await asyncio.to_thread(_jwks_client.get_signing_key_from_jwt, id_token)
    return signing_key.key


async def _verify_id_token(id_token: str, expected_nonce: str) -> dict:
    try:
        key = await _signing_key(id_token)
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=os.environ["GOOGLE_CLIENT_ID"],
            issuer=ISSUERS,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except Exception as exc:
        raise SignInRefused("invalid_id_token") from exc
    if not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise SignInRefused("invalid_id_token")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise SignInRefused("google_email_not_verified")
    return claims


async def _exchange_code(code: str, code_verifier: str) -> str:
    payload = {
        "code": code,
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(TOKEN_URL, data=payload)
    except httpx.HTTPError as exc:
        raise SignInRefused("token_exchange_failed") from exc
    if response.status_code >= 400:
        raise SignInRefused("token_exchange_failed")
    id_token = response.json().get("id_token")
    if not id_token:
        raise SignInRefused("token_exchange_failed")
    return id_token


async def _resolve_user(claims: dict, mode: str, link_user_id: str | None) -> dict:
    sub = str(claims["sub"])
    email = str(claims["email"]).lower()
    name = claims.get("name")
    picture = claims.get("picture")
    by_sub = await db.users.find_one({"google_sub": sub}, {"_id": 0})

    if mode == "link":
        if by_sub and by_sub["user_id"] != link_user_id:
            raise SignInRefused("google_account_used_by_another_user")
        user = await db.users.find_one({"user_id": link_user_id}, {"_id": 0})
        if not user:
            raise SignInRefused("account_not_found")
        if user.get("google_sub") and user["google_sub"] != sub:
            raise SignInRefused("different_google_account_already_linked")
        update = {"google_sub": sub}
        if picture and not user.get("picture"):
            update["picture"] = picture
        try:
            await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
        except DuplicateKeyError as exc:
            raise SignInRefused("google_account_used_by_another_user") from exc
        user.update(update)
        return user

    if by_sub:
        if picture and picture != by_sub.get("picture"):
            await db.users.update_one({"user_id": by_sub["user_id"]}, {"$set": {"picture": picture}})
            by_sub["picture"] = picture
        return by_sub

    by_email = await db.users.find_one({"email": email}, {"_id": 0})
    if by_email:
        if by_email.get("password_hash"):
            raise SignInRefused("password_account_exists")
        if by_email.get("google_sub"):
            raise SignInRefused("different_google_account_already_linked")
        update = {"google_sub": sub, "auth_provider": "google"}
        if picture:
            update["picture"] = picture
        try:
            await db.users.update_one({"user_id": by_email["user_id"]}, {"$set": update})
        except DuplicateKeyError as exc:
            raise SignInRefused("google_account_used_by_another_user") from exc
        by_email.update(update)
        return by_email

    user_id = new_id("user")
    user = {
        "user_id": user_id,
        "email": email,
        "name": name or email.split("@")[0],
        "picture": picture,
        "role": "user",
        "auth_provider": "google",
        "google_sub": sub,
        "beta_approved": True,
        "created_at": now_iso(),
    }
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError as exc:
        # Another request created this email or Google id between our reads.
        raise SignInRefused("sign_in_conflict_try_again") from exc
    user.pop("_id", None)
    await _ensure_workspace(user_id, user["name"])
    return user


@router.get("/status")
async def google_status():
    return {"configured": _configured()}


@router.post("/start")
async def google_start(body: StartRequest, request: Request):
    if not _configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured yet")
    link_user_id = None
    if body.mode == "link":
        link_user_id = (await get_current_user(request))["user_id"]

    state = secrets.token_urlsafe(32)
    oidc_nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    await db.oauth_states.insert_one({
        "nonce": state,
        "type": STATE_TYPE,
        "mode": body.mode,
        "user_id": link_user_id,
        "browser_key_hash": _hash(body.browser_key),
        "oidc_nonce": oidc_nonce,
        "code_verifier": code_verifier,
        "expires_at": (datetime.now(timezone.utc) + STATE_TTL).isoformat(),
        "created_at": now_iso(),
    })
    query = urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": oidc_nonce,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return {"auth_url": f"{AUTH_URL}?{query}"}


@router.get("/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return _landing(error="access_denied" if error == "access_denied" else "google_error")
    if not code or not state:
        return _landing(error="missing_oauth_response")

    saved = await db.oauth_states.find_one_and_delete({"nonce": state, "type": STATE_TYPE})
    if not saved:
        return _landing(error="sign_in_expired_or_already_used")
    if _expired(saved.get("expires_at")):
        return _landing(error="sign_in_expired_or_already_used")

    try:
        id_token = await _exchange_code(code, saved["code_verifier"])
        claims = await _verify_id_token(id_token, saved["oidc_nonce"])
        user = await _resolve_user(claims, saved["mode"], saved.get("user_id"))
    except SignInRefused as refused:
        return _landing(error=refused.reason)

    login_code = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({
        "nonce": _hash(login_code),
        "type": CODE_TYPE,
        "mode": saved["mode"],
        "user_id": user["user_id"],
        "browser_key_hash": saved["browser_key_hash"],
        "expires_at": (datetime.now(timezone.utc) + CODE_TTL).isoformat(),
        "created_at": now_iso(),
    })
    return _landing(code=login_code)


@router.post("/exchange")
async def google_exchange(body: ExchangeRequest, response: Response):
    saved = await db.oauth_states.find_one_and_delete({"nonce": _hash(body.code), "type": CODE_TYPE})
    if (
        not saved
        or _expired(saved.get("expires_at"))
        or not hmac.compare_digest(saved["browser_key_hash"], _hash(body.browser_key))
    ):
        raise HTTPException(
            status_code=401,
            detail="This Google sign-in could not be completed. Start again from this browser tab.",
        )
    user = await db.users.find_one({"user_id": saved["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Account not found")
    token = create_access_token(user["user_id"], user["email"])
    _set_cookie(response, "access_token", token, 7 * 24 * 3600)
    return {"user": _public_user(user), "token": token, "mode": saved["mode"]}
