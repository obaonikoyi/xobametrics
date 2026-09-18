import base64
import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from auth import get_current_user
from database import db
from models import new_id, now_iso

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
REQUIRED_SCOPES = {YOUTUBE_READ_SCOPE, YOUTUBE_ANALYTICS_SCOPE}
SCOPE = " ".join((YOUTUBE_READ_SCOPE, YOUTUBE_ANALYTICS_SCOPE))
STATE_TYPE = "youtube_oauth_state"


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "https://metrics.3xoba.com").strip().rstrip("/")


def _redirect_uri() -> str:
    explicit = os.environ.get("YOUTUBE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    public_api = os.environ.get("PUBLIC_API_URL", "").strip().rstrip("/")
    if not public_api:
        return ""
    return f"{public_api}/api/youtube/callback"


def _configured() -> bool:
    return bool(
        os.environ.get("YOUTUBE_CLIENT_ID")
        and os.environ.get("YOUTUBE_CLIENT_SECRET")
        and _redirect_uri()
    )


def _state_secret() -> str:
    return os.environ["JWT_SECRET"]


def _fernet() -> Fernet:
    raw = os.environ.get("YOUTUBE_TOKEN_ENCRYPTION_KEY") or os.environ.get("JWT_SECRET")
    if not raw:
        raise RuntimeError("Token encryption key is not configured")
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
        raise HTTPException(status_code=500, detail="Stored YouTube credentials cannot be decrypted") from exc


def _oauth_error_redirect(reason: str) -> RedirectResponse:
    safe = reason[:120].replace(" ", "_")
    return RedirectResponse(f"{_frontend_url()}/connections?youtube=error&reason={safe}")


async def _background_history_backfill(profile_id: str, owner_id: str):
    """Run historical import after OAuth without delaying the Google redirect."""
    try:
        from youtube_history import youtube_backfill_history
        await youtube_backfill_history(profile_id=profile_id, user={"user_id": owner_id})
        await db.platform_connections.update_one(
            {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"},
            {"$set": {"history_last_error": None, "history_backfill_status": "complete"}},
        )
    except HTTPException as exc:
        await db.platform_connections.update_one(
            {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"},
            {"$set": {"history_last_error": str(exc.detail)[:300], "history_backfill_status": "error"}},
        )
    except Exception:
        await db.platform_connections.update_one(
            {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"},
            {"$set": {
                "history_last_error": "Historical Analytics import failed. Retry from Connections.",
                "history_backfill_status": "error",
            }},
        )


async def _owned_profile(profile_id: str, user_id: str) -> dict:
    profile = await db.creator_profiles.find_one(
        {"id": profile_id, "owner_id": user_id}, {"_id": 0}
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


async def _refresh_access_token(connection: dict) -> tuple[str, dict]:
    refresh_token = _decrypt(connection.get("refresh_token_enc"))
    if not refresh_token:
        await db.platform_connections.update_one(
            {"id": connection["id"]},
            {"$set": {"status": "needs_reconnect", "last_error": "Missing refresh token"}},
        )
        raise HTTPException(status_code=401, detail="Reconnect YouTube to continue syncing")

    payload = {
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data=payload)
    if response.status_code >= 400:
        await db.platform_connections.update_one(
            {"id": connection["id"]},
            {"$set": {"status": "needs_reconnect", "last_error": "Google token refresh failed"}},
        )
        raise HTTPException(status_code=401, detail="Reconnect YouTube to continue syncing")

    data = response.json()
    access_token = data["access_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
    update = {
        "access_token_enc": _encrypt(access_token),
        "access_token_expires_at": expires_at.isoformat(),
        "status": "connected",
        "last_error": None,
    }
    await db.platform_connections.update_one({"id": connection["id"]}, {"$set": update})
    connection.update(update)
    return access_token, connection


async def _access_token(connection: dict) -> tuple[str, dict]:
    access_token = _decrypt(connection.get("access_token_enc"))
    expires_raw = connection.get("access_token_expires_at")
    expires_at = None
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except Exception:
            expires_at = None
    if access_token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return access_token, connection
    return await _refresh_access_token(connection)


async def _youtube_get(access_token: str, path: str, params: dict) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{YOUTUBE_API}/{path}", params=params, headers=headers)
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="YouTube authorization expired")
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message")
        except Exception:
            message = None
        raise HTTPException(status_code=502, detail=message or "YouTube API request failed")
    return response.json()


async def _channel(access_token: str) -> dict:
    data = await _youtube_get(
        access_token,
        "channels",
        {"part": "snippet,contentDetails,statistics", "mine": "true", "maxResults": 1},
    )
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="No YouTube channel was found for this Google account")
    return items[0]


async def _upload_video_ids(access_token: str, uploads_playlist_id: str) -> list[str]:
    ids: list[str] = []
    page_token = None
    while True:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _youtube_get(access_token, "playlistItems", params)
        for item in data.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                ids.append(video_id)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        # Safety bound for unexpectedly huge channels during the first MVP import.
        if len(ids) >= 2000:
            break
    return ids


async def _videos(access_token: str, ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        data = await _youtube_get(
            access_token,
            "videos",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
        )
        out.extend(data.get("items", []))
    return out


def _int_stat(stats: dict, key: str) -> int:
    try:
        return int(stats.get(key, 0) or 0)
    except Exception:
        return 0


def _thumb(snippet: dict) -> str | None:
    thumbs = snippet.get("thumbnails", {})
    for key in ("maxres", "standard", "high", "medium", "default"):
        if thumbs.get(key, {}).get("url"):
            return thumbs[key]["url"]
    return None


async def _upsert_video(profile: dict, owner_id: str, channel_id: str, video: dict) -> tuple[bool, bool]:
    video_id = video["id"]
    snippet = video.get("snippet", {})
    statistics = video.get("statistics", {})
    published_at = snippet.get("publishedAt") or now_iso()
    publish_date = published_at[:10]

    content = await db.content_items.find_one(
        {"profile_id": profile["id"], "platform": "youtube", "external_id": video_id}, {"_id": 0}
    )
    created_content = False
    if content:
        await db.content_items.update_one(
            {"id": content["id"]},
            {"$set": {
                "title": snippet.get("title") or content.get("title"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": _thumb(snippet),
                "published_at": published_at,
                "channel_id": channel_id,
            }},
        )
    else:
        release_id = new_id("rel")
        title = snippet.get("title") or f"YouTube video {video_id}"
        release = {
            "id": release_id,
            "profile_id": profile["id"],
            "workspace_id": profile["workspace_id"],
            "owner_id": owner_id,
            "title": title,
            "release_date": publish_date,
            "cover": _thumb(snippet) or "#FF0000",
            "description": "Imported automatically from YouTube. Group related content into a campaign later if needed.",
            "source": "youtube",
            "source_external_id": video_id,
            "created_at": now_iso(),
        }
        await db.releases.insert_one(release)
        content = {
            "id": new_id("ci"),
            "release_id": release_id,
            "profile_id": profile["id"],
            "workspace_id": profile["workspace_id"],
            "owner_id": owner_id,
            "title": title,
            "platform": "youtube",
            "content_type": "video",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published_at": published_at,
            "thumbnail": _thumb(snippet),
            "external_id": video_id,
            "channel_id": channel_id,
            "created_at": now_iso(),
        }
        await db.content_items.insert_one(content)
        created_content = True

    today = datetime.now(timezone.utc).date()
    try:
        release_date = datetime.fromisoformat(published_at.replace("Z", "+00:00")).date()
    except Exception:
        release_date = today
    views = _int_stat(statistics, "viewCount")
    likes = _int_stat(statistics, "likeCount")
    comments = _int_stat(statistics, "commentCount")
    snapshot = {
        "id": new_id("snap"),
        "content_item_id": content["id"],
        "release_id": content["release_id"],
        "profile_id": profile["id"],
        "date": today.isoformat(),
        "day_offset": max(0, (today - release_date).days),
        "views": views,
        "plays": 0,
        "likes": likes,
        "comments": comments,
        "shares": 0,
        "followers": 0,
        "reach": views,
        "engagement": likes + comments,
        "source": "youtube_api",
        "unavailable_metrics": ["shares", "followers"],
        "observed_at": now_iso(),
    }
    result = await db.metric_snapshots.update_one(
        {"content_item_id": content["id"], "date": today.isoformat(), "source": "youtube_api"},
        {"$set": snapshot},
        upsert=True,
    )
    created_snapshot = bool(result.upserted_id)
    return created_content, created_snapshot


async def sync_youtube(profile_id: str, owner_id: str) -> dict:
    profile = await _owned_profile(profile_id, owner_id)
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"}, {"_id": 0}
    )
    if not connection or connection.get("status") != "connected":
        raise HTTPException(status_code=400, detail="Connect YouTube before syncing")

    access_token, connection = await _access_token(connection)
    try:
        channel = await _channel(access_token)
    except HTTPException as exc:
        if exc.status_code == 401:
            access_token, connection = await _refresh_access_token(connection)
            channel = await _channel(access_token)
        else:
            raise

    uploads = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        raise HTTPException(status_code=502, detail="YouTube uploads playlist was not returned")
    ids = await _upload_video_ids(access_token, uploads)
    videos = await _videos(access_token, ids)

    imported = 0
    snapshots = 0
    for video in videos:
        created_content, created_snapshot = await _upsert_video(
            profile, owner_id, channel["id"], video
        )
        imported += 1 if created_content else 0
        snapshots += 1 if created_snapshot else 0

    channel_stats = channel.get("statistics", {})
    now = now_iso()
    await db.platform_connections.update_one(
        {"id": connection["id"]},
        {"$set": {
            "status": "connected",
            "account_name": channel.get("snippet", {}).get("title"),
            "external_account_id": channel["id"],
            "last_synced_at": now,
            "last_error": None,
            "channel_statistics": {
                "view_count": _int_stat(channel_stats, "viewCount"),
                "subscriber_count": _int_stat(channel_stats, "subscriberCount"),
                "video_count": _int_stat(channel_stats, "videoCount"),
                "hidden_subscriber_count": bool(channel_stats.get("hiddenSubscriberCount", False)),
            },
        }},
    )
    return {
        "channel": channel.get("snippet", {}).get("title"),
        "channel_id": channel["id"],
        "videos_seen": len(videos),
        "content_imported": imported,
        "snapshots_created": snapshots,
        "synced_at": now,
    }


@router.get("/status")
async def youtube_status(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user["user_id"])
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": user["user_id"], "platform": "youtube"}, {"_id": 0}
    )
    public = None
    if connection:
        public = {k: connection.get(k) for k in (
            "id", "status", "account_name", "external_account_id", "last_synced_at",
            "channel_statistics", "last_error"
        )}
    return {
        "configured": _configured(),
        "redirect_uri": _redirect_uri() if _configured() else None,
        "connection": public,
    }


@router.post("/connect")
async def youtube_connect(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    if not _configured():
        raise HTTPException(status_code=503, detail="YouTube OAuth credentials are not configured yet")
    await _owned_profile(profile_id, user["user_id"])
    nonce = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.oauth_states.insert_one({
        "nonce": nonce,
        "type": STATE_TYPE,
        "owner_id": user["user_id"],
        "profile_id": profile_id,
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
        _state_secret(),
        algorithm="HS256",
    )
    query = urlencode({
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    })
    return {"auth_url": f"{AUTH_URL}?{query}"}


@router.get("/callback")
async def youtube_callback(
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return _oauth_error_redirect(error)
    if not code or not state:
        return _oauth_error_redirect("missing_oauth_response")
    try:
        payload = jwt.decode(state, _state_secret(), algorithms=["HS256"])
        if payload.get("type") != STATE_TYPE:
            raise ValueError("wrong state type")
        nonce = payload["nonce"]
        owner_id = payload["sub"]
        profile_id = payload["profile_id"]
    except Exception:
        return _oauth_error_redirect("invalid_or_expired_state")

    saved = await db.oauth_states.find_one_and_delete(
        {"nonce": nonce, "type": STATE_TYPE, "owner_id": owner_id, "profile_id": profile_id}
    )
    if not saved:
        return _oauth_error_redirect("oauth_state_already_used_or_missing")
    try:
        expires_at = datetime.fromisoformat(saved["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return _oauth_error_redirect("oauth_state_expired")
    except Exception:
        return _oauth_error_redirect("invalid_oauth_state")

    profile = await db.creator_profiles.find_one(
        {"id": profile_id, "owner_id": owner_id}, {"_id": 0}
    )
    if not profile:
        return _oauth_error_redirect("profile_not_found")

    token_payload = {
        "code": code,
        "client_id": os.environ.get("YOUTUBE_CLIENT_ID", ""),
        "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(TOKEN_URL, data=token_payload)
    if response.status_code >= 400:
        return _oauth_error_redirect("token_exchange_failed")
    tokens = response.json()
    granted = set((tokens.get("scope") or "").split())
    missing_scopes = REQUIRED_SCOPES - granted
    if missing_scopes:
        return _oauth_error_redirect("required_youtube_permissions_not_granted")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        return _oauth_error_redirect("missing_access_token")

    try:
        channel = await _channel(access_token)
    except Exception:
        return _oauth_error_redirect("channel_lookup_failed")

    existing = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"}, {"_id": 0}
    )
    connection_id = existing["id"] if existing else new_id("conn")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    update = {
        "id": connection_id,
        "profile_id": profile_id,
        "workspace_id": profile["workspace_id"],
        "owner_id": owner_id,
        "platform": "youtube",
        "source": "oauth",
        "status": "connected",
        "account_name": channel.get("snippet", {}).get("title"),
        "external_account_id": channel["id"],
        "access_token_enc": _encrypt(access_token),
        "access_token_expires_at": expires_at.isoformat(),
        "scopes": list(granted),
        "connected_at": existing.get("connected_at") if existing else now_iso(),
        "last_error": None,
    }
    if refresh_token:
        update["refresh_token_enc"] = _encrypt(refresh_token)
    elif existing and existing.get("refresh_token_enc"):
        update["refresh_token_enc"] = existing["refresh_token_enc"]
    else:
        return _oauth_error_redirect("missing_refresh_token_retry_consent")

    await db.platform_connections.update_one(
        {"id": connection_id}, {"$set": update}, upsert=True
    )
    try:
        result = await sync_youtube(profile_id, owner_id)
        imported = result["content_imported"]
        seen = result["videos_seen"]
        if YOUTUBE_ANALYTICS_SCOPE in granted:
            await db.platform_connections.update_one(
                {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"},
                {"$set": {"history_backfill_status": "running", "history_last_error": None}},
            )
            background_tasks.add_task(_background_history_backfill, profile_id, owner_id)
        return RedirectResponse(
            f"{_frontend_url()}/connections?youtube=connected&imported={imported}&videos={seen}"
        )
    except Exception:
        return RedirectResponse(f"{_frontend_url()}/connections?youtube=connected&sync=failed")


@router.post("/sync")
async def youtube_sync(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    if not _configured():
        raise HTTPException(status_code=503, detail="YouTube OAuth credentials are not configured yet")
    return await sync_youtube(profile_id, user["user_id"])


@router.delete("/disconnect")
async def youtube_disconnect(profile_id: str = Query(...), user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user["user_id"])
    connection = await db.platform_connections.find_one(
        {"profile_id": profile_id, "owner_id": user["user_id"], "platform": "youtube"}, {"_id": 0}
    )
    if not connection:
        return {"ok": True}
    token = _decrypt(connection.get("access_token_enc"))
    if token:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(REVOKE_URL, params={"token": token})
        except Exception:
            pass
    await db.platform_connections.update_one(
        {"id": connection["id"]},
        {"$set": {
            "status": "needs_auth",
            "last_synced_at": None,
            "last_error": None,
        }, "$unset": {
            "access_token_enc": "",
            "refresh_token_enc": "",
            "access_token_expires_at": "",
        }},
    )
    return {"ok": True}
