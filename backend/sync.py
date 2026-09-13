"""Scheduled platform-sync + snapshot worker.

Real platform OAuth is stubbed, so this worker advances the metric time-series
for every *connected* platform instead of live-calling APIs (which the spec
forbids on page load anyway). It is idempotent per day: running it more than
once on the same date is a no-op, so the daily timer and the manual "Refresh
sync" button are both safe.
"""
import math
import random
import logging
from datetime import date, timedelta

from database import db
from models import new_id, now_iso
from analytics import METRIC_KEYS

logger = logging.getLogger("xobametrics.sync")

# platforms whose primary metric is "plays" rather than "views"
PLAYS_PLATFORMS = {"soundcloud"}
# starting values for brand-new content that has no snapshots yet
SEED_START = {"youtube": 800, "soundcloud": 500, "tiktok": 1500, "instagram": 700, "twitter": 400, "csv": 500}


def _grow(last_val: int, age_days: int) -> int:
    if last_val <= 0:
        return 0
    factor = max(0.001, 0.12 * math.exp(-age_days / 25.0))
    jitter = 1 + (random.random() - 0.5) * 0.03
    return int(round(last_val * (1 + factor * jitter)))


def _derive(views, plays, likes, comments, shares, followers):
    reach = views + plays
    return {
        "views": views, "plays": plays, "likes": likes, "comments": comments,
        "shares": shares, "followers": followers, "reach": reach,
        "engagement": likes + comments + shares,
    }


async def sync_content_item(content: dict, today: date) -> bool:
    """Append today's snapshot for one content item. Returns True if created."""
    cid = content["id"]
    release = await db.releases.find_one({"id": content["release_id"]}, {"_id": 0})
    if not release:
        return False
    try:
        rel_date = date.fromisoformat(str(release["release_date"])[:10])
    except Exception:
        rel_date = today
    if rel_date > today:
        return False  # release scheduled in the future — nothing to snapshot yet
    day_offset = (today - rel_date).days

    snaps = await db.metric_snapshots.find({"content_item_id": cid}, {"_id": 0}).to_list(100000)
    latest = None
    for s in snaps:
        if latest is None or s["date"] > latest["date"]:
            latest = s
    today_iso = today.isoformat()
    if latest and latest["date"] >= today_iso:
        return False  # already synced today

    uses_plays = content["platform"] in PLAYS_PLATFORMS
    if latest:
        age = day_offset
        views = _grow(latest.get("views", 0), age)
        plays = _grow(latest.get("plays", 0), age)
        likes = _grow(latest.get("likes", 0), age)
        comments = _grow(latest.get("comments", 0), age)
        shares = _grow(latest.get("shares", 0), age)
        followers = _grow(latest.get("followers", 0), age)
    else:
        base = SEED_START.get(content["platform"], 500) + random.randint(0, 400)
        views = 0 if uses_plays else base
        plays = base if uses_plays else 0
        reach0 = views + plays
        likes = int(reach0 * 0.04)
        comments = int(reach0 * 0.004)
        shares = int(reach0 * 0.007)
        followers = int(reach0 * 0.012)

    metrics = _derive(views, plays, likes, comments, shares, followers)
    doc = {
        "id": new_id("snap"),
        "content_item_id": cid,
        "release_id": content["release_id"],
        "profile_id": content["profile_id"],
        "date": today_iso,
        "day_offset": day_offset,
        **metrics,
    }
    await db.metric_snapshots.insert_one(doc)
    return True


async def sync_connection(connection: dict, today: date = None) -> int:
    """Sync all content on a connection's platform for its profile."""
    today = today or date.today()
    if connection.get("status") != "connected":
        return 0
    content = await db.content_items.find(
        {"profile_id": connection["profile_id"], "platform": connection["platform"]}, {"_id": 0}
    ).to_list(2000)
    created = 0
    for c in content:
        if await sync_content_item(c, today):
            created += 1
    await db.platform_connections.update_one(
        {"id": connection["id"]}, {"$set": {"last_synced_at": now_iso()}})
    return created


async def sync_profile(profile_id: str, today: date = None) -> dict:
    today = today or date.today()
    conns = await db.platform_connections.find(
        {"profile_id": profile_id, "status": "connected"}, {"_id": 0}
    ).to_list(100)
    total = 0
    for conn in conns:
        total += await sync_connection(conn, today)
    return {"connections_synced": len(conns), "snapshots_created": total, "synced_at": now_iso()}


async def run_daily_sync():
    """Background job: refresh every connected platform across all workspaces."""
    today = date.today()
    conns = await db.platform_connections.find({"status": "connected"}, {"_id": 0}).to_list(100000)
    total = 0
    for conn in conns:
        try:
            total += await sync_connection(conn, today)
        except Exception as e:
            logger.error(f"sync failed for connection {conn.get('id')}: {e}")
    logger.info(f"Daily sync complete: {len(conns)} connections, {total} snapshots created")
    return {"connections": len(conns), "snapshots_created": total}
