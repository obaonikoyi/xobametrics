"""SoundCloud OAuth 2.1 + creator track metric sync.

The integration follows SoundCloud's current requirements:
- Authorization Code flow with PKCE (S256)
- Authorization: OAuth <access_token> for API calls
- short-lived access tokens and single-use refresh tokens
- URNs as stable resource identifiers
"""
import base64
import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from auth import get_current_user
from database import db
from models import new_id, now_iso

router = APIRouter(prefix="/api/soundcloud", tags=["soundcloud"])

AUTH_URL = "https://secure.soundcloud.com/authorize"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
SIGN_OUT_URL = "https://secure.soundcloud.com/sign-out"
API_BASE = "https://api.soundcloud.com"
STATE_TYPE = "soundcloud_oauth_state"


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "https://metrics.3xoba.com").strip().rstrip("/")


def _redirect_uri() -> str:
    explicit = os.environ.get("SOUNDCLOUD_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    public_api = os.environ.get("PUBLIC_API_URL", "").strip().rstrip("/")
    return f"{public_api}/api/soundcloud/callback" if public_api else ""


def _configured() -> bool:
    return bool(
        os.environ.get("SOUNDCLOUD_CLIENT_ID")
        and os.environ.get("SOUNDCLOUD_CLIENT_SECRET")
        and os.environ.get("SOUNDCLOUD_TOKEN_ENCRYPTION_KEY")
        and _redirect_uri()
    )


def _fernet() -> Fernet:
    raw = os.environ.get("SOUNDCLOUD_TOKEN_ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError("SoundCloud token encryption key is not configured")
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Stored SoundCloud credentials cannot be decrypted") from exc


def _pkce_verifier() -> str:
    # token_urlsafe produces URL-safe entropy and stays inside PKCE's 43-128 range.
    return secrets.token_urlsafe(64)[:96]


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _error_redirect(reason: str) -> RedirectResponse:
    safe = reason[:120].replace(" ", "_")
    return RedirectResponse(f"{_frontend_url()}/connections?soundcloud=error&reason={safe}")


async def _owned_profile(profile_id: str, owner_id: str) -> dict:
    profile = await db.creator_profiles.find_one(
        {"id": profile_id, "owner_id": owner_id}, {"_id": 0}
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _token_expiry(data: dict) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in") or 3600))
    ).isoformat()


async def _refresh_access_token(connection: dict) -> tuple[str, dict]:
    refresh_token = _decrypt(connection.get("refresh_token_enc"))
    if not refresh_token:
        await db.platform_connections.update_one(
            {"id": connection["id"]},
            {"$set": {"status": "needs_reconnect", "last_error": "Missing SoundCloud refresh token"}},
        )
        raise HTTPException(status_code=401, detail="Reconnect SoundCloud to continue syncing")

    payload = {
        "grant_type": "refresh_token",
        "client_id": os.environ["SOUNDCLOUD_CLIENT_ID"],
        "client_secret": os.environ["SOUNDCLOUD_CLIENT_SECRET"],
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        await db.platform_connections.update_one(
            {"id": connection["id"]},
            {"$set": {"status": "needs_reconnect", "last_error": "SoundCloud token refresh failed"}},
        )
        raise HTTPException(status_code=401, detail="Reconnect SoundCloud to continue syncing")

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="SoundCloud did not return an access token")
    update = {
        "access_token_enc": _encrypt(access_token),
        "access_token_expires_at": _token_expiry(data),
        "status": "connected",
        "last_error": None,
    }
    # SoundCloud refresh tokens are single-use. Replace the stored token whenever
    # the refresh response gives us a new one.
    if data.get("refresh_token"):
        update["refresh_token_enc"] = _encrypt(data["refresh_token"])
    await db.platform_connections.update_one({"id": connection["id"]}, {"$set": update})
    connection.update(update)
    return access_token, connection


async def _access_token(connection: dict) -> tuple[str, dict]:
    token = _decrypt(connection.get("access_token_enc"))
    expires_at = None
    raw = connection.get("access_token_expires_at")
    if raw:
        try:
            expires_at = datetime.fromisoformat(raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    if token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return token, connection
    return await _refresh_access_token(connection)


async def _api_get(access_token: str, path_or_url: str, params: dict | None = None) -> dict | list:
    if path_or_url.startswith("http"):
        parsed = urlparse(path_or_url)
        if parsed.scheme != "https" or parsed.hostname != "api.soundcloud.com":
            raise HTTPException(status_code=502, detail="SoundCloud returned an unsafe pagination URL")
        url = path_or_url
    else:
        url = f"{API_BASE}/{path_or_url.lstrip('/')}"
    headers = {
        "Authorization": f"OAuth {access_token}",
        "Accept": "application/json; charset=utf-8",
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.get(url, params=params, headers=headers)
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="SoundCloud authorization expired")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="SoundCloud rate limit reached. Try again later.")
    if response.status_code >= 400:
        message = None
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("error")
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=message or "SoundCloud API request failed")
    return response.json()


async def _me(access_token: str) -> dict:
    data = await _api_get(access_token, "/me")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected SoundCloud account response")
    return data


async def _owned_tracks(access_token: str) -> list[dict]:
    tracks: list[dict] = []
    next_url: str | None = f"{API_BASE}/me/tracks"
    params = {"limit": 200, "linked_partitioning": "true"}
    pages = 0
    while next_url and pages < 100:
        payload = await _api_get(access_token, next_url, params if pages == 0 else None)
        pages += 1
        if isinstance(payload, list):
            tracks.extend(x for x in payload if isinstance(x, dict))
            break
        if not isinstance(payload, dict):
            break
        collection = payload.get("collection")
        if isinstance(collection, list):
            tracks.extend(x for x in collection if isinstance(x, dict))
        next_url = payload.get("next_href")
        if not next_url:
            break
    return tracks


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _track_urn(track: dict) -> str | None:
    urn = track.get("urn")
    if urn:
        return str(urn)
    legacy_id = track.get("id")
    return f"soundcloud:tracks:{legacy_id}" if legacy_id is not None else None


def _track_date(track: dict) -> str:
    raw = str(track.get("created_at") or now_iso())
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return raw[:10] if len(raw) >= 10 else datetime.now(timezone.utc).date().isoformat()


async def _upsert_track(profile: dict, owner_id: str, track: dict) -> tuple[bool, bool]:
    urn = _track_urn(track)
    if not urn:
        return False, False
    title = str(track.get("title") or "Untitled SoundCloud track")
    permalink = track.get("permalink_url")
    artwork = track.get("artwork_url")
    publish_date = _track_date(track)

    content = await db.content_items.find_one(
        {"profile_id": profile["id"], "platform": "soundcloud", "external_id": urn},
        {"_id": 0},
    )
    created_content = False
    if content:
        await db.content_items.update_one(
            {"id": content["id"]},
            {"$set": {
                "title": title,
                "url": permalink,
                "thumbnail": artwork,
                "published_at": track.get("created_at") or publish_date,
                "soundcloud_urn": urn,
            }},
        )
    else:
        release = {
            "id": new_id("rel"),
            "profile_id": profile["id"],
            "workspace_id": profile["workspace_id"],
            "owner_id": owner_id,
            "title": title,
            "release_date": publish_date,
            "cover": artwork or "#FF5500",
            "description": "Imported automatically from SoundCloud. Merge with the matching campaign when appropriate.",
            "source": "soundcloud",
            "source_external_id": urn,
            "created_at": now_iso(),
        }
        await db.releases.insert_one(release)
        content = {
            "id": new_id("ci"),
            "release_id": release["id"],
            "profile_id": profile["id"],
            "workspace_id": profile["workspace_id"],
            "owner_id": owner_id,
            "title": title,
            "platform": "soundcloud",
            "content_type": "track",
            "url": permalink,
            "published_at": track.get("created_at") or publish_date,
            "thumbnail": artwork,
            "external_id": urn,
            "soundcloud_urn": urn,
            "created_at": now_iso(),
        }
        await db.content_items.insert_one(content)
        created_content = True

    today = datetime.now(timezone.utc).date()
    try:
        release_date = datetime.fromisoformat(
            str(content.get("published_at") or publish_date).replace("Z", "+00:00")
        ).date()
    except Exception:
        release_date = today

    plays = _safe_int(track.get("playback_count"))
    likes = _safe_int(track.get("favoritings_count"))
    comments = _safe_int(track.get("comment_count"))
    reposts = _safe_int(track.get("reposts_count"))
    snapshot = {
        "id": new_id("snap"),
        "content_item_id": content["id"],
        "release_id": content["release_id"],
        "profile_id": profile["id"],
        "date": today.isoformat(),
        "day_offset": max(0, (today - release_date).days),
        "views": 0,
        "plays": plays,
        "likes": likes,
        "comments": comments,
        "shares": reposts,
        "followers": 0,
        "reach": plays,
        "engagement": likes + comments + reposts,
        "source": "soundcloud_api",
        "metric_semantics": "current_cumulative_track_counters",
        "observed_at": now_iso(),
    }
    result = await db.metric_snapshots.update_one(
        {
            "content_item_id": content["id"],
            "date": today.isoformat(),
            "source": "soundcloud_api",
        },
        {"$set": snapshot},
        upsert=True,
    )
    return created_content, bool(result.upserted_id)


async def sync_soundcloud(profile_id: str, owner_id: str) -> dict:
    profile = await _owned_profile(profile_id, owner_id)
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": owner_id, "platform": "soundcloud"},
        {"_id": 0},
    )
    if not connection or connection.get("status") != "connected":
        raise HTTPException(status_code=400, detail="Connect SoundCloud before syncing")
    token, connection = await _access_token(connection)
    try:
        account = await _me(token)
        tracks = await _owned_tracks(token)
    except HTTPException as exc:
        if exc.status_code == 401:
            token, connection = await _refresh_access_token(connection)
            account = await _me(token)
            tracks = await _owned_tracks(token)
        else:
            raise

    imported = 0
    snapshots = 0
    for track in tracks:
        created, snap_created = await _upsert_track(profile, owner_id, track)
        imported += 1 if created else 0
        snapshots += 1 if snap_created else 0

    now = now_iso()
    await db.platform_connections.update_one(
        {"id": connection["id"]},
        {"$set": {
            "status": "connected",
            "account_name": account.get("username"),
            "external_account_id": str(account.get("urn") or account.get("id") or ""),
            "last_synced_at": now,
            "last_error": None,
            "account_statistics": {
                "followers_count": _safe_int(account.get("followers_count")),
                "followings_count": _safe_int(account.get("followings_count")),
                "track_count": _safe_int(account.get("track_count")),
            },
        }},
    )
    return {
        "account": account.get("username"),
        "tracks_seen": len(tracks),
        "content_imported": imported,
        "snapshots_created": snapshots,
        "synced_at": now,
    }


@router.get("/status")
async def soundcloud_status(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user["user_id"])
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": user["user_id"], "platform": "soundcloud"},
        {"_id": 0},
    )
    public = None
    if connection:
        public = {k: connection.get(k) for k in (
            "id", "status", "account_name", "external_account_id",
            "last_synced_at", "account_statistics", "last_error",
        )}
    return {
        "configured": _configured(),
        "redirect_uri": _redirect_uri() if _configured() else None,
        "connection": public,
    }


@router.post("/connect")
async def soundcloud_connect(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    if not _configured():
        raise HTTPException(status_code=503, detail="SoundCloud OAuth credentials are not configured yet")
    await _owned_profile(profile_id, user["user_id"])
    nonce = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.oauth_states.insert_one({
        "nonce": nonce,
        "type": STATE_TYPE,
        "owner_id": user["user_id"],
        "profile_id": profile_id,
        "pkce_verifier_enc": _encrypt(verifier),
        "expires_at": expires_at.isoformat(),
        "created_at": now_iso(),
    })
    state = jwt.encode(
        {
            "type": STATE_TYPE,
            "nonce": nonce,
            "sub": user["user_id"],
            "profile_id": profile_id,
            "exp": expires_at,
        },
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    query = urlencode({
        "client_id": os.environ["SOUNDCLOUD_CLIENT_ID"],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
    })
    return {"auth_url": f"{AUTH_URL}?{query}"}


@router.get("/callback")
async def soundcloud_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return _error_redirect(error)
    if not code or not state:
        return _error_redirect("missing_oauth_response")
    try:
        payload = jwt.decode(state, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != STATE_TYPE:
            raise ValueError("wrong state type")
        nonce = payload["nonce"]
        owner_id = payload["sub"]
        profile_id = payload["profile_id"]
    except Exception:
        return _error_redirect("invalid_or_expired_state")

    saved = await db.oauth_states.find_one_and_delete(
        {"nonce": nonce, "type": STATE_TYPE, "owner_id": owner_id, "profile_id": profile_id}
    )
    if not saved:
        return _error_redirect("oauth_state_already_used_or_missing")
    try:
        saved_expiry = datetime.fromisoformat(saved["expires_at"])
        if saved_expiry.tzinfo is None:
            saved_expiry = saved_expiry.replace(tzinfo=timezone.utc)
        if saved_expiry < datetime.now(timezone.utc):
            return _error_redirect("oauth_state_expired")
        verifier = _decrypt(saved.get("pkce_verifier_enc"))
        if not verifier:
            return _error_redirect("missing_pkce_verifier")
    except Exception:
        return _error_redirect("invalid_oauth_state")

    profile = await db.creator_profiles.find_one(
        {"id": profile_id, "owner_id": owner_id}, {"_id": 0}
    )
    if not profile:
        return _error_redirect("profile_not_found")

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": os.environ.get("SOUNDCLOUD_CLIENT_ID", ""),
        "client_secret": os.environ.get("SOUNDCLOUD_CLIENT_SECRET", ""),
        "redirect_uri": _redirect_uri(),
        "code_verifier": verifier,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data=token_payload,
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        return _error_redirect("token_exchange_failed")
    tokens = response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token or not refresh_token:
        return _error_redirect("missing_soundcloud_tokens")

    try:
        account = await _me(access_token)
    except Exception:
        return _error_redirect("account_lookup_failed")

    existing = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": owner_id, "platform": "soundcloud"},
        {"_id": 0},
    )
    connection_id = existing["id"] if existing else new_id("conn")
    update = {
        "id": connection_id,
        "profile_id": profile_id,
        "workspace_id": profile["workspace_id"],
        "owner_id": owner_id,
        "platform": "soundcloud",
        "source": "oauth",
        "status": "connected",
        "account_name": account.get("username"),
        "external_account_id": str(account.get("urn") or account.get("id") or ""),
        "access_token_enc": _encrypt(access_token),
        "refresh_token_enc": _encrypt(refresh_token),
        "access_token_expires_at": _token_expiry(tokens),
        "scopes": tokens.get("scope"),
        "connected_at": existing.get("connected_at") if existing else now_iso(),
        "last_error": None,
    }
    await db.platform_connections.update_one(
        {"id": connection_id}, {"$set": update}, upsert=True
    )
    try:
        result = await sync_soundcloud(profile_id, owner_id)
        return RedirectResponse(
            f"{_frontend_url()}/connections?soundcloud=connected&tracks={result['tracks_seen']}&imported={result['content_imported']}"
        )
    except Exception:
        return RedirectResponse(f"{_frontend_url()}/connections?soundcloud=connected&sync=failed")


@router.post("/sync")
async def soundcloud_sync(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    if not _configured():
        raise HTTPException(status_code=503, detail="SoundCloud OAuth credentials are not configured yet")
    return await sync_soundcloud(profile_id, user["user_id"])


@router.delete("/disconnect")
async def soundcloud_disconnect(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user["user_id"])
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": user["user_id"], "platform": "soundcloud"},
        {"_id": 0},
    )
    if not connection:
        return {"ok": True}
    token = _decrypt(connection.get("access_token_enc"))
    if token:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    SIGN_OUT_URL,
                    json={"access_token": token},
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            pass
    await db.platform_connections.update_one(
        {"id": connection["id"]},
        {
            "$set": {"status": "needs_auth", "last_synced_at": None, "last_error": None},
            "$unset": {
                "access_token_enc": "",
                "refresh_token_enc": "",
                "access_token_expires_at": "",
            },
        },
    )
    return {"ok": True}
