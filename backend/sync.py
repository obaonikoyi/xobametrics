"""Background real-data sync dispatcher.

Only adapters that retrieve real platform data belong here. Synthetic growth is
forbidden. YouTube and SoundCloud are the currently implemented adapters.
"""
import logging
from datetime import datetime, timezone

from database import db

logger = logging.getLogger("xobametrics.sync")
LIVE_PLATFORMS = {"youtube", "soundcloud"}
INTEGRATION_MESSAGE = (
    "This platform does not have a live sync adapter yet. Upload a CSV export instead."
)


async def sync_content_item(content: dict, today=None) -> bool:
    """Per-item synthetic/carry-forward updates are deliberately unsupported."""
    return False


async def sync_connection(connection: dict, today=None) -> int:
    if connection.get("status") != "connected":
        return 0
    platform = connection.get("platform")
    if platform == "youtube":
        from youtube import sync_youtube
        result = await sync_youtube(connection["profile_id"], connection["owner_id"])
    elif platform == "soundcloud":
        from soundcloud import sync_soundcloud
        result = await sync_soundcloud(connection["profile_id"], connection["owner_id"])
    else:
        return 0
    return int(result.get("snapshots_created", 0))


async def sync_profile(profile_id: str, today=None) -> dict:
    connections = await db.platform_connections.find(
        {
            "profile_id": profile_id,
            "status": "connected",
            "platform": {"$in": sorted(LIVE_PLATFORMS)},
        },
        {"_id": 0},
    ).to_list(100)
    snapshots = 0
    synced = 0
    for connection in connections:
        platform = connection.get("platform")
        try:
            snapshots += await sync_connection(connection, today)
            synced += 1
        except Exception as exc:
            logger.error(
                "%s sync failed for connection %s: %s",
                platform,
                connection.get("id"),
                exc,
            )
    return {
        "status": "ok",
        "connections_synced": synced,
        "snapshots_created": snapshots,
        "synced_at": datetime.now(timezone.utc).isoformat() if synced else None,
    }


async def run_daily_sync():
    """Refresh each profile that has at least one live connected adapter."""
    connections = await db.platform_connections.find(
        {
            "status": "connected",
            "platform": {"$in": sorted(LIVE_PLATFORMS)},
        },
        {"_id": 0},
    ).to_list(100000)
    seen = set()
    profiles = 0
    snapshots = 0
    for connection in connections:
        key = (connection.get("owner_id"), connection.get("profile_id"))
        if key in seen or not all(key):
            continue
        seen.add(key)
        try:
            result = await sync_profile(connection["profile_id"])
            profiles += 1
            snapshots += int(result.get("snapshots_created", 0))
        except Exception as exc:
            logger.error("Daily sync failed for profile %s: %s", connection.get("profile_id"), exc)
    logger.info(
        "Daily real-data sync complete: %s profiles, %s new snapshots",
        profiles,
        snapshots,
    )
    return {
        "status": "ok",
        "profiles": profiles,
        "snapshots_created": snapshots,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
