import os
import jwt
import bcrypt
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends

from database import db
from models import RegisterRequest, LoginRequest, new_id, now_iso

JWT_ALGORITHM = "HS256"

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
    # JWT access token (cookie or Bearer)
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


@auth_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _public_user(user)


@auth_router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}
