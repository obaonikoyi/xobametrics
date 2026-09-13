import math
import random
from datetime import date, timedelta
from database import db
from models import new_id, now_iso

RELEASES = [
    {"title": "Take It Easy", "days_ago": 120, "cover": "#3B82F6",
     "content": [
         ("Take It Easy (Official Video)", "youtube", "video", 480000),
         ("Take It Easy - Short #1", "youtube", "short", 260000),
         ("Take It Easy", "soundcloud", "track", 320000),
         ("TIE TikTok Promo", "tiktok", "promo", 540000),
         ("Take It Easy Reel", "instagram", "reel", 190000),
     ]},
    {"title": "Midnight Signal", "days_ago": 45, "cover": "#34D399",
     "content": [
         ("Midnight Signal (Visualizer)", "youtube", "video", 210000),
         ("Midnight Signal", "soundcloud", "track", 175000),
         ("Midnight Signal TikTok", "tiktok", "promo", 300000),
     ]},
    {"title": "Neon Rain", "days_ago": 8, "cover": "#FBBF24",
     "content": [
         ("Neon Rain (Official Video)", "youtube", "video", 95000),
         ("Neon Rain", "soundcloud", "track", 60000),
         ("Neon Rain Reel", "instagram", "reel", 78000),
     ]},
]

CONNECTIONS = [
    ("youtube", "connected", "Luna Eclipse — YT", "oauth"),
    ("soundcloud", "connected", "luna-eclipse", "oauth"),
    ("tiktok", "needs_reconnect", "@lunaeclipse", "oauth"),
    ("instagram", "needs_auth", None, "oauth"),
    ("csv", "connected", "Manual uploads", "csv"),
]


def _curve(total, day, age, rnd):
    """Cumulative value at `day` for a content item that is `age` days old."""
    k = 0.06 + rnd.random() * 0.03
    frac = 1 - math.exp(-k * (day + 1))
    jitter = 1 + (rnd.random() - 0.5) * 0.04
    return max(0, int(total * frac * jitter))


async def seed_demo(owner_id: str, workspace_id: str, profile_id: str):
    existing = await db.releases.find_one({"profile_id": profile_id}, {"_id": 0})
    if existing:
        return {"seeded": False, "reason": "already has data"}

    rnd = random.Random(42)
    today = date.today()

    # connections
    for platform, status, account, source in CONNECTIONS:
        await db.platform_connections.insert_one({
            "id": new_id("conn"),
            "profile_id": profile_id,
            "workspace_id": workspace_id,
            "owner_id": owner_id,
            "platform": platform,
            "status": status,
            "account_name": account,
            "source": source,
            "connected_at": now_iso(),
            "last_synced_at": (now_iso() if status == "connected" else None),
        })

    snap_docs = []
    for rel in RELEASES:
        release_date = today - timedelta(days=rel["days_ago"])
        release_id = new_id("rel")
        await db.releases.insert_one({
            "id": release_id,
            "profile_id": profile_id,
            "workspace_id": workspace_id,
            "owner_id": owner_id,
            "title": rel["title"],
            "release_date": release_date.isoformat(),
            "cover": rel["cover"],
            "description": f"{rel['title']} — cross-platform release campaign.",
            "created_at": now_iso(),
        })
        age = rel["days_ago"]
        for title, platform, ctype, total in rel["content"]:
            content_id = new_id("ci")
            await db.content_items.insert_one({
                "id": content_id,
                "release_id": release_id,
                "profile_id": profile_id,
                "workspace_id": workspace_id,
                "owner_id": owner_id,
                "title": title,
                "platform": platform,
                "content_type": ctype,
                "url": None,
                "published_at": release_date.isoformat(),
                "thumbnail": None,
                "created_at": now_iso(),
            })
            uses_plays = platform == "soundcloud"
            span = min(age, 120)
            for d in range(0, span + 1):
                primary = _curve(total, d, age, rnd)
                views = 0 if uses_plays else primary
                plays = primary if uses_plays else 0
                reach = views + plays
                likes = int(reach * (0.035 + rnd.random() * 0.02))
                comments = int(reach * 0.004)
                shares = int(reach * 0.007)
                followers = int(reach * 0.012)
                snap_date = release_date + timedelta(days=d)
                snap_docs.append({
                    "id": new_id("snap"),
                    "content_item_id": content_id,
                    "release_id": release_id,
                    "profile_id": profile_id,
                    "date": snap_date.isoformat(),
                    "day_offset": d,
                    "views": views,
                    "plays": plays,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "reach": reach,
                    "engagement": likes + comments + shares,
                    "followers": followers,
                })
    if snap_docs:
        await db.metric_snapshots.insert_many(snap_docs)
    return {"seeded": True, "releases": len(RELEASES), "snapshots": len(snap_docs)}
