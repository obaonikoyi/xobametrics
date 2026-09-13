from datetime import date
from database import db

# canonical metric keys stored on snapshots
METRIC_KEYS = ["views", "plays", "likes", "comments", "shares", "reach", "engagement", "followers"]

PLATFORM_META = {
    "youtube": {"label": "YouTube", "color": "#FF0000", "primary": "views"},
    "soundcloud": {"label": "SoundCloud", "color": "#FF5500", "primary": "plays"},
    "tiktok": {"label": "TikTok", "color": "#00F2FE", "primary": "views"},
    "instagram": {"label": "Instagram", "color": "#E1306C", "primary": "views"},
    "twitter": {"label": "X / Twitter", "color": "#1D9BF0", "primary": "views"},
    "csv": {"label": "CSV Import", "color": "#3B82F6", "primary": "plays"},
}

RACE_COLORS = ["#3B82F6", "#34D399", "#FBBF24", "#A78BFA", "#F43F5E", "#38BDF8"]


def _parse_date(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


async def _content_for_release(release_id: str):
    return await db.content_items.find({"release_id": release_id}, {"_id": 0}).to_list(1000)


async def _latest_snapshots_by_content(content_ids):
    """Return the most recent (max date) snapshot per content item."""
    if not content_ids:
        return {}
    snaps = await db.metric_snapshots.find(
        {"content_item_id": {"$in": content_ids}}, {"_id": 0}
    ).to_list(200000)
    latest = {}
    for s in snaps:
        cid = s["content_item_id"]
        if cid not in latest or s["date"] > latest[cid]["date"]:
            latest[cid] = s
    return latest


def _empty_totals():
    return {k: 0 for k in METRIC_KEYS}


async def release_totals(release_id: str) -> dict:
    content = await _content_for_release(release_id)
    cids = [c["id"] for c in content]
    latest = await _latest_snapshots_by_content(cids)
    totals = _empty_totals()
    per_platform = {}
    last_synced = None
    for c in content:
        snap = latest.get(c["id"])
        if not snap:
            continue
        plat = c["platform"]
        per_platform.setdefault(plat, _empty_totals())
        for k in METRIC_KEYS:
            v = snap.get(k, 0) or 0
            totals[k] += v
            per_platform[plat][k] += v
        if last_synced is None or snap["date"] > last_synced:
            last_synced = snap["date"]
    return {
        "totals": totals,
        "per_platform": per_platform,
        "content_count": len(content),
        "last_synced": last_synced,
    }


async def profile_overview(profile_id: str) -> dict:
    releases = await db.releases.find({"profile_id": profile_id}, {"_id": 0}).to_list(1000)
    grand = _empty_totals()
    per_platform = {}
    release_rows = []
    last_synced = None
    for r in releases:
        rt = await release_totals(r["id"])
        for k in METRIC_KEYS:
            grand[k] += rt["totals"][k]
        for plat, vals in rt["per_platform"].items():
            per_platform.setdefault(plat, _empty_totals())
            for k in METRIC_KEYS:
                per_platform[plat][k] += vals[k]
        if rt["last_synced"] and (last_synced is None or rt["last_synced"] > last_synced):
            last_synced = rt["last_synced"]
        release_rows.append({
            "id": r["id"],
            "title": r["title"],
            "release_date": r["release_date"],
            "cover": r.get("cover"),
            "reach": rt["totals"]["reach"],
            "engagement": rt["totals"]["engagement"],
            "content_count": rt["content_count"],
        })
    release_rows.sort(key=lambda x: x["reach"], reverse=True)
    platform_breakdown = [
        {"platform": p, "label": PLATFORM_META.get(p, {}).get("label", p),
         "color": PLATFORM_META.get(p, {}).get("color", "#3B82F6"),
         "reach": v["reach"], "engagement": v["engagement"]}
        for p, v in per_platform.items()
    ]
    platform_breakdown.sort(key=lambda x: x["reach"], reverse=True)
    return {
        "totals": grand,
        "release_count": len(releases),
        "releases": release_rows,
        "platform_breakdown": platform_breakdown,
        "top_release": release_rows[0] if release_rows else None,
        "last_synced": last_synced,
    }


async def release_timeseries(release_id: str, metric: str = "reach") -> dict:
    content = await _content_for_release(release_id)
    cids = [c["id"] for c in content]
    snaps = await db.metric_snapshots.find(
        {"content_item_id": {"$in": cids}}, {"_id": 0}
    ).to_list(200000) if cids else []
    by_date = {}
    for s in snaps:
        d = s["date"]
        by_date.setdefault(d, 0)
        by_date[d] += s.get(metric, 0) or 0
    series = [{"date": d, "value": by_date[d]} for d in sorted(by_date)]
    return {"metric": metric, "series": series}


async def release_race(profile_id: str, release_ids, metric: str = "reach", max_day: int = 90) -> dict:
    results = []
    for i, rid in enumerate(release_ids):
        release = await db.releases.find_one({"id": rid, "profile_id": profile_id}, {"_id": 0})
        if not release:
            continue
        content = await _content_for_release(rid)
        cids = [c["id"] for c in content]
        snaps = await db.metric_snapshots.find(
            {"content_item_id": {"$in": cids}}, {"_id": 0}
        ).to_list(200000) if cids else []
        by_offset = {}
        for s in snaps:
            off = s.get("day_offset")
            if off is None or off < 0 or off > max_day:
                continue
            by_offset.setdefault(off, 0)
            by_offset[off] += s.get(metric, 0) or 0
        series = [{"day": off, "value": by_offset[off]} for off in sorted(by_offset)]
        results.append({
            "release_id": rid,
            "title": release["title"],
            "release_date": release["release_date"],
            "color": RACE_COLORS[i % len(RACE_COLORS)],
            "series": series,
        })
    return {"metric": metric, "max_day": max_day, "releases": results}
