from fastapi import HTTPException

from database import db

# canonical metric keys stored on snapshots
METRIC_KEYS = ["views", "plays", "likes", "comments", "shares", "reach", "engagement", "followers"]

PLATFORM_META = {
    # Direct API (real OAuth, phased)
    "youtube": {"label": "YouTube", "color": "#FF0000", "primary": "views"},
    "soundcloud": {"label": "SoundCloud", "color": "#FF5500", "primary": "plays"},
    "tiktok": {"label": "TikTok", "color": "#00BCD4", "primary": "views"},
    "instagram": {"label": "Instagram", "color": "#E1306C", "primary": "views"},
    "twitter": {"label": "X / Twitter", "color": "#1D9BF0", "primary": "views"},
    # Import via export / CSV (no open metrics API or policy-restricted)
    "spotify": {"label": "Spotify", "color": "#1DB954", "primary": "plays"},
    "apple_music": {"label": "Apple Music", "color": "#FA243C", "primary": "plays"},
    "youtube_music": {"label": "YouTube Music", "color": "#FF0000", "primary": "plays"},
    "amazon_music": {"label": "Amazon Music", "color": "#25D1DA", "primary": "plays"},
    "pandora": {"label": "Pandora", "color": "#3668FF", "primary": "plays"},
    "deezer": {"label": "Deezer", "color": "#A238FF", "primary": "plays"},
    "tidal": {"label": "TIDAL", "color": "#5B7A9A", "primary": "plays"},
    "iheartradio": {"label": "iHeartRadio", "color": "#C6002B", "primary": "plays"},
    "qobuz": {"label": "Qobuz", "color": "#0061FF", "primary": "plays"},
    "bandcamp": {"label": "Bandcamp", "color": "#629AA9", "primary": "plays"},
    "beatport": {"label": "Beatport", "color": "#00C46A", "primary": "plays"},
    "audiomack": {"label": "Audiomack", "color": "#FF8800", "primary": "plays"},
    "boomplay": {"label": "Boomplay", "color": "#E72C30", "primary": "plays"},
    "csv": {"label": "CSV Import", "color": "#3B82F6", "primary": "plays"},
}

# Platforms whose primary metric is streams/plays (not views). Used by CSV ingest + sync.
PLAYS_PLATFORMS = {p for p, m in PLATFORM_META.items() if m["primary"] == "plays" and p != "csv"} | {"csv"}

RACE_COLORS = ["#3B82F6", "#34D399", "#FBBF24", "#A78BFA", "#F43F5E", "#38BDF8"]


# When one item has observations from several sources on the same day, the
# most authoritative wins: completed-day Analytics history, then the live
# YouTube counter, then everything else (CSV, SoundCloud, demo).
_PRIORITY = (
    "CASE s.source WHEN 'youtube_analytics_history' THEN 30 "
    "WHEN 'youtube_api' THEN 20 ELSE 10 END"
)

# The newest observation per content item, after the same-day tie-break.
_LATEST_SNAPSHOTS = f"""
    SELECT DISTINCT ON (s.content_item_id) s.*
    FROM metric_snapshots s
    JOIN content_items c ON c.id = s.content_item_id
    WHERE {{scope}}
    ORDER BY s.content_item_id, s.date DESC, {_PRIORITY} DESC
"""

# One observation per content item per day, after the same-day tie-break.
_DAILY_SNAPSHOTS = f"""
    SELECT DISTINCT ON (s.content_item_id, s.date) s.*, c.release_id AS item_release_id
    FROM metric_snapshots s
    JOIN content_items c ON c.id = s.content_item_id
    WHERE {{scope}}
    ORDER BY s.content_item_id, s.date, {_PRIORITY} DESC
"""


def _metric(metric: str) -> str:
    if metric not in METRIC_KEYS:
        raise HTTPException(status_code=422, detail=f"Unknown metric: {metric}")
    return metric


def _empty_totals():
    return {k: 0 for k in METRIC_KEYS}


def empty_release_totals() -> dict:
    return {"totals": _empty_totals(), "per_platform": {}, "content_count": 0, "last_synced": None}


async def _latest_snapshots_by_content(content_ids):
    """Return the most recent snapshot per content item, de-duping same-day sources."""
    if not content_ids:
        return {}
    rows = await db.fetch(
        _LATEST_SNAPSHOTS.format(scope="s.content_item_id = ANY($1)"), list(content_ids)
    )
    return {r["content_item_id"]: r for r in rows}


async def _rollups(scope: str, arg) -> dict:
    """Totals per release from each content item's latest observation."""
    rows = await db.fetch(
        f"""
        WITH latest AS ({_LATEST_SNAPSHOTS.format(scope=scope)})
        SELECT c.release_id, c.platform, l.date AS snap_date,
               {", ".join(f"l.{k}" for k in METRIC_KEYS)}
        FROM content_items c
        LEFT JOIN latest l ON l.content_item_id = c.id
        WHERE {scope}
        """,
        arg,
    )
    out: dict = {}
    for r in rows:
        rt = out.setdefault(r["release_id"], empty_release_totals())
        rt["content_count"] += 1
        if r["snap_date"] is None:
            continue
        plat = rt["per_platform"].setdefault(r["platform"], _empty_totals())
        for k in METRIC_KEYS:
            v = r[k] or 0
            rt["totals"][k] += v
            plat[k] += v
        if rt["last_synced"] is None or r["snap_date"] > rt["last_synced"]:
            rt["last_synced"] = r["snap_date"]
    return out


async def release_totals(release_id: str) -> dict:
    rollups = await _rollups("c.release_id = $1", release_id)
    return rollups.get(release_id) or empty_release_totals()


async def profile_release_totals(profile_id: str) -> dict:
    """release_totals for every release of a profile, in one query."""
    return await _rollups("c.profile_id = $1", profile_id)


async def profile_overview(profile_id: str) -> dict:
    releases = await db.find("releases", {"profile_id": profile_id})
    rollups = await profile_release_totals(profile_id)
    grand = _empty_totals()
    per_platform = {}
    release_rows = []
    last_synced = None
    for r in releases:
        rt = rollups.get(r["id"]) or empty_release_totals()
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
            "followers": rt["totals"]["followers"],
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
    column = _metric(metric)
    rows = await db.fetch(
        f"""
        WITH daily AS ({_DAILY_SNAPSHOTS.format(scope="c.release_id = $1")})
        SELECT date, sum({column})::bigint AS value FROM daily GROUP BY date ORDER BY date
        """,
        release_id,
    )
    return {"metric": metric, "series": [{"date": r["date"], "value": r["value"]} for r in rows]}


async def release_race(profile_id: str, release_ids, metric: str = "reach", max_day: int = 90) -> dict:
    column = _metric(metric)
    releases = {
        r["id"]: r for r in await db.find("releases", {"id": list(release_ids), "profile_id": profile_id})
    }
    rows = await db.fetch(
        f"""
        WITH daily AS ({_DAILY_SNAPSHOTS.format(scope="c.release_id = ANY($1)")})
        SELECT d.item_release_id AS release_id, (d.date - r.release_date) AS day,
               sum(d.{column})::bigint AS value
        FROM daily d JOIN releases r ON r.id = d.item_release_id
        WHERE (d.date - r.release_date) BETWEEN 0 AND $2
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        list(releases), int(max_day),
    )
    series: dict = {}
    for r in rows:
        series.setdefault(r["release_id"], []).append({"day": r["day"], "value": r["value"]})
    results = []
    for i, rid in enumerate(release_ids):
        release = releases.get(rid)
        if not release:
            continue
        results.append({
            "release_id": rid,
            "title": release["title"],
            "release_date": release["release_date"],
            "color": RACE_COLORS[i % len(RACE_COLORS)],
            "series": series.get(rid, []),
        })
    return {"metric": metric, "max_day": max_day, "releases": results}
