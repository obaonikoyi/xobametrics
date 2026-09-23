import hmac
import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends

from database import db
from models import RegisterRequest, LoginRequest, new_id, now_iso

JWT_ALGORITHM = "HS256"
SESSION_TTL = timedelta(days=7)

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


def invite_codes() -> list[str]:
    """Sign-up is invite-only when BETA_INVITE_CODES lists any codes."""
    return [c.strip() for c in os.environ.get("BETA_INVITE_CODES", "").split(",") if c.strip()]


def invite_code_valid(code: str | None) -> bool:
    codes = invite_codes()
    if not codes:
        return True
    given = (code or "").strip()
    # Compare against every code so timing does not reveal which one is close.
    return any([hmac.compare_digest(given, c) for c in codes]) and bool(given)


def _set_cookie(response: Response, key: str, value: str, max_age: int):
    response.set_cookie(
        key=key, value=value, httponly=True, secure=True,
        samesite="none", max_age=max_age, path="/",
    )


async def issue_session(response: Response, user: dict) -> str:
    """Record a new session and return an access token that names it."""
    session_id = new_id("sess")
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    await db.insert("user_sessions", {
        "id": session_id,
        "user_id": user["user_id"],
        "expires_at": expires_at,
    })
    token = jwt.encode(
        {
            "sub": user["user_id"],
            "email": user["email"],
            "sid": session_id,
            "exp": expires_at,
            "type": "access",
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    _set_cookie(response, "access_token", token, int(SESSION_TTL.total_seconds()))
    return token


def _public_user(user: dict) -> dict:
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "role": user.get("role", "user"),
        "auth_provider": user.get("auth_provider", "password"),
        "google_linked": bool(user.get("google_sub")),
    }


async def _ensure_workspace(user_id: str, name: str) -> dict:
    ws = await db.find_one("workspaces", {"owner_id": user_id})
    if ws:
        return ws
    ws = {
        "id": new_id("ws"),
        "owner_id": user_id,
        "name": name,
        "type": "solo",
        "created_at": now_iso(),
    }
    async with db.transaction():
        await db.insert("workspaces", ws)
        await db.insert("creator_profiles", {
            "id": new_id("prof"),
            "workspace_id": ws["id"],
            "owner_id": user_id,
            "name": name,
            "genre": None,
            "avatar": None,
            "created_at": now_iso(),
        })
    return ws


def _request_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token or None


def _session_payload(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "access" or not payload.get("sid"):
        return None
    return payload


async def get_current_user(request: Request) -> dict:
    payload = _session_payload(_request_token(request))
    if payload:
        user = await db.fetchrow(
            """
            SELECT u.* FROM user_sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.id = $1 AND s.user_id = $2 AND s.revoked_at IS NULL AND s.expires_at > now()
            """,
            payload["sid"], payload["sub"],
        )
        if user:
            return user
    raise HTTPException(status_code=401, detail="Not authenticated")


@auth_router.get("/signup-policy")
async def signup_policy():
    return {"invite_required": bool(invite_codes())}


@auth_router.post("/register")
async def register(body: RegisterRequest, response: Response):
    if not invite_code_valid(body.invite_code):
        raise HTTPException(status_code=403, detail="A valid invite code is required to join the private beta")
    email = body.email.lower()
    existing = await db.find_one("users", {"email": email})
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
    async with db.transaction():
        await db.insert("users", user)
        await _ensure_workspace(user_id, body.name)
    token = await issue_session(response, user)
    return {"user": _public_user(user), "token": token}


@auth_router.post("/login")
async def login(body: LoginRequest, response: Response, request: Request):
    email = body.email.lower()
    ident = f"{request.client.host if request.client else 'x'}:{email}"
    attempt = await db.find_one("login_attempts", {"identifier": ident})
    if attempt and attempt.get("count", 0) >= 5:
        locked_until = attempt.get("locked_until")
        if locked_until and datetime.fromisoformat(locked_until) > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = await db.find_one("users", {"email": email})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        await db.execute(
            """
            INSERT INTO login_attempts (identifier, count, locked_until) VALUES ($1, 1, $2)
            ON CONFLICT (identifier) DO UPDATE
            SET count = login_attempts.count + 1, locked_until = EXCLUDED.locked_until
            """,
            ident, datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await db.delete("login_attempts", {"identifier": ident})
    token = await issue_session(response, user)
    return {"user": _public_user(user), "token": token}


@auth_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _public_user(user)


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    try:
        payload = _session_payload(_request_token(request))
    except HTTPException:
        payload = None
    if payload:
        await db.update(
            "user_sessions",
            {"id": payload["sid"], "user_id": payload["sub"], "revoked_at": None},
            {"revoked_at": datetime.now(timezone.utc)},
        )
    response.delete_cookie("access_token", path="/")
    return {"ok": True}
