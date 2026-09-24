"""Historical YouTube Analytics backfill.

YouTube Data API snapshots provide current cumulative counts. The YouTube
Analytics API provides dated activity, which we convert to cumulative
observations aligned to each video's real publish date for Release Race.

Days YouTube leaves out after publication had no activity; days it has not
processed yet are left out rather than guessed.
"""
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from database import NOT_NULL, db
from models import new_id, now_iso
from youtube import (
    YOUTUBE_ANALYTICS_SCOPE,
    _access_token,
    _owned_profile,
)

router = APIRouter(prefix="/api/youtube", tags=["youtube"])
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
HISTORY_SOURCE = "youtube_analytics_history"
HISTORY_METRICS = ("views", "likes", "comments", "shares", "subscribersGained")


def _scope_granted(connection: dict | None) -> bool:
    return bool(connection and YOUTUBE_ANALYTICS_SCOPE in set(connection.get("scopes") or []))


async def _connection(profile_id: str, owner_id: str) -> dict | None:
    return await db.find_one(
        "platform_connections",
        {"profile_id": profile_id, "owner_id": owner_id, "platform": "youtube"},
    )


async def _analytics_query(access_token: str, params: dict) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(ANALYTICS_API, params=params, headers=headers)
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Reconnect YouTube to refresh Analytics permission")
    if response.status_code >= 400:
        message = None
        reason = None
        try:
            payload = response.json().get("error", {})
            message = payload.get("message")
            errors = payload.get("errors") or []
            reason = errors[0].get("reason") if errors else None
        except Exception:
            pass
        if response.status_code == 403 and (
            reason == "accessNotConfigured"
            or "has not been used" in (message or "")
            or "disabled" in (message or "").lower()
        ):
            raise HTTPException(
                status_code=503,
                detail="Enable the YouTube Analytics API in the XobaMetrics Google Cloud project, then retry.",
            )
        if response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="YouTube Analytics permission is not available for this connection. Reconnect YouTube and approve the requested read-only permissions.",
            )
        raise HTTPException(status_code=502, detail=message or "YouTube Analytics request failed")
    return response.json()


def _rows_as_dicts(payload: dict) -> list[dict]:
    headers = [h.get("name") for h in payload.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in payload.get("rows", [])]


async def _fetch_history(access_token: str, video_ids: list[str], start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    # Google allows up to 500 IDs in a video filter. Smaller batches keep the
    # response comfortably bounded and make failures easier to retry.
    for batch_start in range(0, len(video_ids), 100):
        batch = video_ids[batch_start:batch_start + 100]
        start_index = 1
        while True:
            params = {
                "ids": "channel==MINE",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "metrics": ",".join(HISTORY_METRICS),
                "dimensions": "day,video",
                "filters": "video==" + ",".join(batch),
                "sort": "day,video",
                "maxResults": 200,
                "startIndex": start_index,
            }
            payload = await _analytics_query(access_token, params)
            page_rows = _rows_as_dicts(payload)
            rows.extend(page_rows)
            if len(page_rows) < 200:
                break
            start_index += len(page_rows)
    return rows


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _published_date(content: dict) -> date | None:
    raw = str(content.get("published_at") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except Exception:
        return None


@router.get("/history-status")
async def youtube_history_status(
    profile_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    await _owned_profile(profile_id, user["user_id"])
    connection = await _connection(profile_id, user["user_id"])
    return {
        "scope_granted": _scope_granted(connection),
        "backfilled_at": connection.get("history_backfilled_at") if connection else None,
        "history_start_date": connection.get("history_start_date") if connection else None,
        "history_end_date": connection.get("history_end_date") if connection else None,
        "history_points_written": connection.get("history_points_written", 0) if connection else 0,
        "history_rows_received": connection.get("history_rows_received", 0) if connection else 0,
        "history_last_error": connection.get("history_last_error") if connection else None,
        "backfill_status": connection.get("history_backfill_status") if connection else None,
    }


@router.post("/backfill-history")
async def youtube_backfill_history(
    profile_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    await _owned_profile(profile_id, user["user_id"])
    connection = await _connection(profile_id, user["user_id"])
    if not connection or connection.get("status") != "connected":
        raise HTTPException(status_code=400, detail="Connect YouTube before importing history")
    if not _scope_granted(connection):
        raise HTTPException(
            status_code=409,
            detail="Reconnect YouTube once to grant read-only YouTube Analytics history permission.",
        )
    return await backfill_history(profile_id, user["user_id"], connection)


def _cumulative_series(published: date, day_rows: dict[date, dict], through: date):
    """
    Cumulative totals for every day from the publish date to `through`.

    YouTube Analytics leaves out days with no activity, so a missing day after
    publication is a real zero, and the series starts at Day 0 even when the
    first views came later. Analytics days are Pacific time while the publish
    date is UTC, so activity dated before it (at most a day) belongs to Day 0.
    """
    cumulative = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "followers": 0}
    for d, row in day_rows.items():
        if d < published:
            for key in cumulative:
                cumulative[key] += row[key]
    d = published
    while d <= through:
        row = day_rows.get(d)
        if row:
            for key in cumulative:
                cumulative[key] += row[key]
        yield d, dict(cumulative)
        d += timedelta(days=1)


async def backfill_history(profile_id: str, owner_id: str, connection: dict, published_since: date | None = None) -> dict:
    """
    Import daily YouTube Analytics history as cumulative snapshots.

    `published_since` limits the import to recent videos; the daily sync uses
    it so a new release gets its Day 0 once YouTube has processed the data.
    """
    content_items = await db.find("content_items", {
        "profile_id": profile_id,
        "owner_id": owner_id,
        "platform": "youtube",
        "external_id": NOT_NULL,
    })
    usable = [
        c for c in content_items
        if _published_date(c) and (published_since is None or _published_date(c) >= published_since)
    ]
    if not usable:
        return {
            "status": "ok",
            "videos": 0,
            "rows_received": 0,
            "history_points_written": 0,
            "message": "No imported YouTube videos were available for history backfill.",
        }

    # Pacific-time Analytics days can start a day before the UTC publish date.
    start_date = min(_published_date(c) for c in usable) - timedelta(days=1)
    # Analytics data can lag behind public counters; keep the current UTC day
    # exclusively for the normal Data API snapshot path.
    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    if start_date >= end_date:
        return {
            "status": "ok",
            "videos": len(usable),
            "rows_received": 0,
            "history_points_written": 0,
            "message": "The imported videos are too new for historical Analytics data yet.",
        }

    access_token, connection = await _access_token(connection)
    rows = await _fetch_history(
        access_token,
        [c["external_id"] for c in usable],
        start_date,
        end_date,
    )

    content_by_video = {c["external_id"]: c for c in usable}
    daily: dict[str, dict[date, dict]] = {}
    for row in rows:
        video_id = row.get("video")
        raw_day = row.get("day")
        if video_id not in content_by_video or not raw_day:
            continue
        try:
            d = date.fromisoformat(str(raw_day)[:10])
        except Exception:
            continue
        daily.setdefault(video_id, {})[d] = {
            "views": _safe_int(row.get("views")),
            "likes": _safe_int(row.get("likes")),
            "comments": _safe_int(row.get("comments")),
            "shares": _safe_int(row.get("shares")),
            "followers": _safe_int(row.get("subscribersGained")),
        }

    # YouTube processes Analytics a day or more behind. Days after the latest
    # one it has reported for any video are unknown, not zero, and would
    # otherwise outrank the live counters for those days.
    reported_through = max((d for day_rows in daily.values() for d in day_rows), default=None)

    snapshots = []
    now = now_iso()
    for video_id, day_rows in daily.items():
        content = content_by_video[video_id]
        published = _published_date(content)
        for d, totals in _cumulative_series(published, day_rows, reported_through):
            snapshots.append({
                "id": new_id("snap"),
                "content_item_id": content["id"],
                "release_id": content["release_id"],
                "profile_id": profile_id,
                "date": d.isoformat(),
                "day_offset": (d - published).days,
                "views": totals["views"],
                "plays": 0,
                "likes": totals["likes"],
                "comments": totals["comments"],
                "shares": totals["shares"],
                "followers": totals["followers"],
                "reach": totals["views"],
                "engagement": totals["likes"] + totals["comments"] + totals["shares"],
                "source": HISTORY_SOURCE,
                "metric_semantics": "cumulative_from_daily_youtube_analytics_activity",
                "history_first_observed_date": min(day_rows).isoformat(),
                "observed_at": now,
            })

    async with db.transaction():
        if reported_through is not None:
            # Earlier imports carried totals past what YouTube had reported.
            await db.execute(
                "DELETE FROM metric_snapshots WHERE source = $1 AND content_item_id = ANY($2) AND date > $3",
                HISTORY_SOURCE, [c["id"] for c in usable], reported_through,
            )
        for start in range(0, len(snapshots), 1000):
            await db.upsert_many(
                "metric_snapshots", snapshots[start:start + 1000],
                conflict=("content_item_id", "date", "source"), keep=("id",),
            )

    finished = now_iso()
    if published_since is None:
        await db.update(
            "platform_connections",
            {"id": connection["id"]},
            {
                "history_backfilled_at": finished,
                "history_start_date": start_date.isoformat(),
                "history_end_date": end_date.isoformat(),
                "history_rows_received": len(rows),
                "history_points_written": len(snapshots),
                "history_last_error": None,
            },
        )
    return {
        "status": "ok",
        "videos": len(usable),
        "rows_received": len(rows),
        "history_points_written": len(snapshots),
        "database_writes": len(snapshots),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "backfilled_at": finished,
    }
