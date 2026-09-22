import os
import jwt
import bcrypt
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends
import requests

from database import db
from models import RegisterRequest, LoginRequest, SessionRequest, new_id, now_iso

JWT_ALGORITHM = "HS256"

# Sign-in delegated to the scaffolding vendor's demo host.
#
# POST /api/auth/session takes a session id from the caller, asks this host who
# it belongs to, and signs in -- or creates -- an account for whatever email
# comes back, already beta approved. Nothing is verified locally: no signature,
# no issuer, no audience. The whole guarantee is that the remote host is honest
# and reachable, and the host is named "demobackend".
#
# So it is off unless a deployment explicitly turns it on, and it is not the
# way to add Google sign-in. The right fix is a real Google OAuth flow, which
# this codebase already knows how to do -- see youtube.py, which does the
# authorization code exchange against accounts.google.com and validates scopes.
EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
EMERGENT_LOGIN_ENABLED = (
    os.environ.get("ENABLE_EMERGENT_GOOGLE_LOGIN", "false").strip().lower() == "true"
)

auth_router = APIRouter(prefix="/api/auth")


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _set_cookie(response: Response, key: str, value: str, max_age: int):
    response.set_cookie(
        key=key, value=value, httponly=True, secure=True,
        samesite="none", max_age=max_age, path="/",
    )


def _public_user(user: dict) -> dict:
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "role": user.get("role", "user"),
        "auth_provider": user.get("auth_provider", "password"),
    }


async def _ensure_workspace(user_id: str, name: str) -> dict:
    ws = await db.workspaces.find_one({"owner_id": user_id}, {"_id": 0})
    if ws:
        return ws
    ws = {
        "id": new_id("ws"),
        "owner_id": user_id,
        "name": name,
        "type": "solo",
        "created_at": now_iso(),
    }
    await db.workspaces.insert_one(ws)
    profile = {
        "id": new_id("prof"),
        "workspace_id": ws["id"],
        "owner_id": user_id,
        "name": name,
        "genre": None,
        "avatar": None,
        "created_at": now_iso(),
    }
    await db.creator_profiles.insert_one(profile)
    return ws


async def get_current_user(request: Request) -> dict:
    # 1. Google session_token (cookie or Bearer)
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            maybe = auth_header[7:]
            sess = await db.user_sessions.find_one({"session_token": maybe}, {"_id": 0})
            if sess:
                session_token = maybe
    if session_token:
        sess = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if sess:
            expires_at = sess["expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at >= datetime.now(timezone.utc):
                user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
                if user:
                    return user

    # 2. JWT access token (cookie or Bearer)
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if token:
        try:
            payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
            if payload.get("type") == "access":
                user = await db.users.find_one({"user_id": payload["sub"]}, {"_id": 0})
                if user:
                    return user
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            pass

    raise HTTPException(status_code=401, detail="Not authenticated")


@auth_router.post("/register")
async def register(body: RegisterRequest, response: Response):
    email = body.email.lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    user_id = new_id("user")
    user = {
        "user_id": user_id,
        "email": email,
        "name": body.name,
        "password_hash": hash_password(body.password),
        "role": "user",
        "auth_provider": "password",
        "beta_approved": True,
        "created_at": now_iso(),
    }
    await db.users.insert_one(user)
    await _ensure_workspace(user_id, body.name)
    token = create_access_token(user_id, email)
    _set_cookie(response, "access_token", token, 7 * 24 * 3600)
    return {"user": _public_user(user), "token": token}


@auth_router.post("/login")
async def login(body: LoginRequest, response: Response, request: Request):
    email = body.email.lower()
    ident = f"{request.client.host if request.client else 'x'}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": ident}, {"_id": 0})
    if attempt and attempt.get("count", 0) >= 5:
        locked_until = attempt.get("locked_until")
        if locked_until:
            lu = datetime.fromisoformat(locked_until) if isinstance(locked_until, str) else locked_until
            if lu.tzinfo is None:
                lu = lu.replace(tzinfo=timezone.utc)
            if lu > datetime.now(timezone.utc):
                raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        await db.login_attempts.update_one(
            {"identifier": ident},
            {"$inc": {"count": 1}, "$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}},
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await db.login_attempts.delete_one({"identifier": ident})
    token = create_access_token(user["user_id"], email)
    _set_cookie(response, "access_token", token, 7 * 24 * 3600)
    return {"user": _public_user(user), "token": token}


@auth_router.post("/session")
async def google_session(body: SessionRequest, response: Response):
    if not EMERGENT_LOGIN_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="This sign-in method is disabled. Use email and password.",
        )
    try:
        r = requests.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": body.session_id}, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception:
        raise HTTPException(status_code=401, detail="Google authentication failed")

    email = data["email"].lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = new_id("user")
        user = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name"),
            "picture": data.get("picture"),
            "role": "user",
            "auth_provider": "google",
            "beta_approved": True,
            "created_at": now_iso(),
        }
        await db.users.insert_one(user)
        await _ensure_workspace(user_id, data.get("name") or email.split("@")[0])
    else:
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"picture": data.get("picture")}})
        await _ensure_workspace(user["user_id"], user.get("name") or email.split("@")[0])

    session_token = data["session_token"]
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": now_iso(),
    })
    _set_cookie(response, "session_token", session_token, 7 * 24 * 3600)
    return {"user": _public_user(user), "token": session_token}


@auth_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _public_user(user)


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("session_token", path="/")
    return {"ok": True}
