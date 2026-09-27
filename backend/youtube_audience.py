"""
Where YouTube views come from, and which countries watch.

Both come from the YouTube Analytics API under the read-only Analytics
permission the history import already asks for, for the whole channel or for
the videos of one release. Answers are kept for REPORT_TTL so opening a page
does not query YouTube each time.
"""
import hashlib
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from database import NOT_NULL, db
from youtube import _access_token, _owned_profile
from youtube_history import _analytics_query, _connection, _rows_as_dicts, _scope_granted

router = APIRouter(prefix="/api/youtube", tags=["youtube"])
REPORT_TTL = timedelta(hours=6)
TOP_COUNTRIES = 15
MAX_VIDEOS = 200

# YouTube's traffic source codes, in words an artist recognises.
TRAFFIC_SOURCES = {
    "YT_SEARCH": "YouTube search",
    "SUGGESTED": "Suggested next to other videos",
    "RELATED_VIDEO": "Suggested next to other videos",
    "BROWSE": "Home page & browsing",
    "SUBSCRIBER": "Subscriptions feed",
    "NOTIFICATION": "Notifications",
    "SHORTS": "Shorts feed",
    "SHORTS_CONTENT_LINKS": "Links in Shorts",
    "SOUND_PAGE": "Shorts sound page",
    "HASHTAGS": "Hashtag pages",
    "VIDEO_REMIXES": "Remixes of your videos",
    "PLAYLIST": "Playlists",
    "YT_PLAYLIST_PAGE": "Playlist pages",
    "YT_CHANNEL": "Your channel page",
    "CHANNEL": "Your channel page",
    "END_SCREEN": "End screens",
    "ANNOTATION": "Cards & annotations",
    "CAMPAIGN_CARD": "Cards & annotations",
    "EXT_URL": "Other websites & apps",
    "NO_LINK_EMBEDDED": "Embedded on other sites",
    "NO_LINK_OTHER": "Direct or unknown",
    "YT_OTHER_PAGE": "Other YouTube pages",
    "ADVERTISING": "YouTube ads",
    "PROMOTED": "YouTube ads",
    "LIVE_REDIRECT": "Live redirects",
    "IMMERSIVE_LIVE": "Live",
    "PRODUCT_PAGE": "Product pages",
}


def _label(code: str) -> str:
    return TRAFFIC_SOURCES.get(code) or code.replace("_", " ").capitalize()


def _shares(rows: list[tuple[str, int]], total: int | None = None) -> list[dict]:
    total = total or sum(v for _, v in rows) or 1
    return [{"key": k, "views": v, "share": round(v / total, 4)} for k, v in rows]


def _merge_labels(rows: list[dict]) -> list[dict]:
    """Several codes share a label (e.g. SUGGESTED and RELATED_VIDEO); add them up."""
    merged: dict[str, int] = {}
    for row in rows:
        label = _label(str(row.get("insightTrafficSourceType") or "NO_LINK_OTHER"))
        merged[label] = merged.get(label, 0) + int(row.get("views") or 0)
    return sorted(merged.items(), key=lambda kv: kv[1], reverse=True)


async def _video_ids(profile_id: str, owner_id: str, release_id: str | None) -> list[str] | None:
    """None for the whole channel; otherwise the release's YouTube videos."""
    if not release_id:
        return None
    release = await db.find_one("releases", {"id": release_id, "profile_id": profile_id, "owner_id": owner_id})
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    items = await db.find("content_items", {
        "release_id": release_id, "platform": "youtube", "external_id": NOT_NULL,
    })
    return sorted({c["external_id"] for c in items})[:MAX_VIDEOS]


async def _report(access_token: str, start: date, end: date, videos: list[str] | None) -> dict:
    base = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(), "metrics": "views"}
    if videos:
        base["filters"] = "video==" + ",".join(videos)
    traffic = _rows_as_dicts(await _analytics_query(access_token, {
        **base, "dimensions": "insightTrafficSourceType", "sort": "-views",
    }))
    countries = _rows_as_dicts(await _analytics_query(access_token, {
        **base, "dimensions": "country", "sort": "-views", "maxResults": TOP_COUNTRIES,
    }))
    sources = _merge_labels(traffic)
    # Countries are the top few only, so their shares are out of all views
    # (every view has a traffic source), not out of the countries listed.
    total = sum(v for _, v in sources)
    country_views = [(str(c.get("country") or "ZZ"), int(c.get("views") or 0)) for c in countries]
    return {
        "total_views": total,
        "traffic": [{"source": s["key"], "views": s["views"], "share": s["share"]} for s in _shares(sources)],
        "countries": [{"country": s["key"], "views": s["views"], "share": s["share"]}
                      for s in _shares(country_views, total)],
    }


@router.get("/audience")
async def youtube_audience(
    profile_id: str = Query(...),
    release_id: str | None = Query(None),
    days: int = Query(28, ge=7, le=365),
    user: dict = Depends(get_current_user),
):
    await _owned_profile(profile_id, user["user_id"])
    videos = await _video_ids(profile_id, user["user_id"], release_id)
    if videos == []:
        return {"status": "no_videos", "traffic": [], "countries": []}
    connection = await _connection(profile_id, user["user_id"])
    if not connection or connection.get("status") != "connected":
        return {"status": "not_connected", "traffic": [], "countries": []}
    if not _scope_granted(connection):
        return {"status": "needs_permission", "traffic": [], "countries": []}

    # Analytics lags a day or two; the window ends yesterday. A release's
    # window starts no earlier than its release date.
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    if release_id:
        release = await db.find_one("releases", {"id": release_id})
        start = max(start, date.fromisoformat(str(release["release_date"])[:10]))
    if start > end:
        return {"status": "too_new", "traffic": [], "countries": [], "start": start.isoformat(), "end": end.isoformat()}

    scope = ",".join(videos) if videos else "channel"
    key = "audience:" + hashlib.sha256(f"{scope}|{start}|{end}".encode()).hexdigest()[:32]
    cached = await db.find_one("youtube_reports", {"profile_id": profile_id, "report_key": key})
    if cached and datetime.fromisoformat(str(cached["fetched_at"])) > datetime.now(timezone.utc) - REPORT_TTL:
        report = cached["rows"]
    else:
        access_token, _ = await _access_token(connection)
        report = await _report(access_token, start, end, videos)
        await db.upsert("youtube_reports", {
            "profile_id": profile_id, "report_key": key, "rows": report,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }, conflict=("profile_id", "report_key"))
    return {"status": "ok", "start": start.isoformat(), "end": end.isoformat(), **report}
