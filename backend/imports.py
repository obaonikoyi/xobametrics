"""
Uploading platform and distributor files.

POST /api/imports/preview says what a file is and what importing it would do,
without writing anything. POST /api/imports/commit imports a distributor
report. Single-song daily exports (Spotify for Artists and the like) keep
using /api/csv/upload and /api/csv/commit; the preview only names the
platform the file probably came from so the form can start with it chosen.
"""
import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

import sales_import
from auth import get_current_user
from database import db
from models import new_id, now_iso

router = APIRouter(prefix="/api/imports", tags=["imports"])
MAX_REPORT_BYTES = 20 * 1024 * 1024
MAX_REPORT_ROWS = 200_000
SOURCE = "distributor"

# Filename hints for single-song exports; only used to preselect the platform.
PLATFORM_HINTS = [
    ("spotify", "spotify"), ("apple", "apple_music"), ("amazon", "amazon_music"), ("deezer", "deezer"),
    ("tiktok", "tiktok"), ("instagram", "instagram"), ("soundcloud", "soundcloud"), ("audiomack", "audiomack"),
    ("youtube", "youtube"), ("boomplay", "boomplay"), ("tidal", "tidal"),
]


async def _owned_profile(profile_id: str, user: dict) -> dict:
    prof = await db.find_one("creator_profiles", {"id": profile_id, "owner_id": user["user_id"]})
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    return prof


async def _read_upload(request: Request, file: UploadFile) -> tuple[list[str], list[dict]]:
    if request.headers.get("x-requested-with") != "XobaMetrics":
        raise HTTPException(status_code=403, detail="Invalid request origin")
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Excel files aren't supported yet. Open it and save as CSV, then upload that.")
    if name.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Unzip the download first and upload the CSV inside it.")
    if not name.endswith((".csv", ".tsv", ".txt")):
        raise HTTPException(status_code=400, detail="Upload a .csv, .tsv or .txt file.")
    raw = await file.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB). Filter it to fewer months and try again.")
    headers, rows = sales_import.read_table(raw)
    if not headers:
        raise HTTPException(status_code=400, detail="That file has no header row.")
    if len(rows) > MAX_REPORT_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {MAX_REPORT_ROWS:,}). Filter it to fewer months.")
    return headers, rows


@router.post("/preview")
async def preview(request: Request, file: UploadFile = File(...), profile_id: str = Form(...),
                  user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    headers, rows = await _read_upload(request, file)
    if sales_import.is_sales_report(headers):
        summary = sales_import.summarise(sales_import.parse_report(headers, rows))
        return {"kind": "sales_report", "filename": file.filename, "rows": len(rows), **summary}
    name = (file.filename or "").lower()
    hint = next((p for needle, p in PLATFORM_HINTS if needle in name), None)
    return {"kind": "daily", "filename": file.filename, "platform_hint": hint, "headers": headers}


def _month_end(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


async def _rebuild_snapshots(item_ids: list[str]) -> int:
    """Each item's running total at the end of every month it has sales for."""
    if not item_ids:
        return 0
    await db.execute("DELETE FROM metric_snapshots WHERE content_item_id = ANY($1) AND source = $2", item_ids, SOURCE)
    rows = await db.fetch(
        """
        SELECT l.content_item_id, c.release_id, c.profile_id, r.release_date, l.month, sum(l.units)::bigint AS units
        FROM sales_lines l
        JOIN content_items c ON c.id = l.content_item_id
        JOIN releases r ON r.id = c.release_id
        WHERE l.content_item_id = ANY($1)
        GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 5
        """,
        item_ids,
    )
    today = date.today()
    snapshots, running = [], {}
    for r in rows:
        total = running.get(r["content_item_id"], 0) + max(int(r["units"]), 0)
        running[r["content_item_id"]] = total
        day = min(_month_end(date.fromisoformat(str(r["month"]))), today)
        snapshots.append({
            "id": new_id("snap"), "content_item_id": r["content_item_id"], "release_id": r["release_id"],
            "profile_id": r["profile_id"], "date": day,
            "day_offset": (day - date.fromisoformat(str(r["release_date"]))).days,
            "plays": total, "reach": total, "source": SOURCE,
            "metric_semantics": "cumulative_monthly_units_from_distributor_report",
        })
    if snapshots:
        await db.insert_many("metric_snapshots", snapshots)
    return len(snapshots)


@router.post("/commit")
async def commit(request: Request, file: UploadFile = File(...), profile_id: str = Form(...),
                 artists: str = Form(""), user: dict = Depends(get_current_user)):
    prof = await _owned_profile(profile_id, user)
    headers, rows = await _read_upload(request, file)
    if not sales_import.is_sales_report(headers):
        raise HTTPException(status_code=400, detail="That file isn't a sales or streaming report.")
    parsed = sales_import.parse_report(headers, rows)
    chosen = set(json.loads(artists)) if artists else None
    lines = [ln for ln in parsed["lines"] if chosen is None or ln["artist"] in chosen]
    if not lines:
        raise HTTPException(status_code=400, detail="No rows to import for the chosen artists.")

    owner = user["user_id"]
    base = {"profile_id": profile_id, "workspace_id": prof["workspace_id"], "owner_id": owner}
    releases = await db.find("releases", {"profile_id": profile_id})
    by_title = {sales_import.normalise_title(r["title"]): r for r in releases}
    items = [c for c in await db.find("content_items", {"profile_id": profile_id})
             if str(c.get("external_id") or "").startswith("dist:")]
    item_by_key = {c["external_id"]: c for c in items}
    release_by_song = {c["external_id"].split(":")[1]: c["release_id"] for c in items}

    new_releases, new_items = [], []
    songs = {}
    for ln in lines:
        songs.setdefault(ln["song_key"], []).append(ln)
    async with db.transaction():
        for song_key, song_lines in songs.items():
            title = song_lines[0]["title"]
            release_id = release_by_song.get(song_key) or (by_title.get(sales_import.normalise_title(title)) or {}).get("id")
            if not release_id:
                first_month = min(ln["month"] for ln in song_lines)
                release = {"id": new_id("rel"), **base, "title": title, "release_date": first_month,
                           "cover": "#3B82F6", "source": SOURCE,
                           "description": "Imported from a distributor report. Day 0 is the first month with sales; set the real release date here.",
                           "created_at": now_iso()}
                await db.insert("releases", release)
                new_releases.append(release)
                by_title[sales_import.normalise_title(title)] = release
                release_id = release["id"]
            release_by_song[song_key] = release_id
            for platform in {ln["platform"] for ln in song_lines}:
                key = f"dist:{song_key}:{platform}"
                if key not in item_by_key:
                    item = {"id": new_id("ci"), **base, "release_id": release_id,
                            "title": title if platform != "csv" else f"{title} (other stores)",
                            "platform": platform, "content_type": "track", "external_id": key,
                            "published_at": min(ln["month"] for ln in song_lines).isoformat(),
                            "created_at": now_iso()}
                    await db.insert("content_items", item)
                    new_items.append(item)
                    item_by_key[key] = item

        merged: dict[tuple, dict] = {}
        for ln in lines:
            item_id = item_by_key[f"dist:{ln['song_key']}:{ln['platform']}"]["id"]
            row = merged.setdefault((item_id, ln["country"], ln["month"]), {
                "content_item_id": item_id, "profile_id": profile_id, "country": ln["country"],
                "month": ln["month"], "store": ln["store"], "units": 0, "earnings": 0.0, "imported_at": now_iso(),
            })
            row["units"] += int(round(ln["units"]))
            row["earnings"] += ln["earnings"]
        await db.upsert_many("sales_lines", list(merged.values()), conflict=("content_item_id", "country", "month"))
        touched = sorted({k[0] for k in merged})
        snapshots = await _rebuild_snapshots(touched)

    return {
        "status": "ok",
        "songs": len(songs),
        "new_releases": [{"id": r["id"], "title": r["title"]} for r in new_releases],
        "new_items": len(new_items),
        "lines": len(merged),
        "snapshots": snapshots,
        "skipped": parsed["skipped"],
    }


@router.get("/countries")
async def countries(profile_id: str = Query(...), release_id: str | None = Query(None),
                    months: int = Query(12, ge=1, le=120), user: dict = Depends(get_current_user)):
    """Streams by country across every store, from imported reports."""
    await _owned_profile(profile_id, user)
    scope, args = "l.profile_id = $1", [profile_id]
    if release_id:
        scope += " AND c.release_id = $2"
        args.append(release_id)
    span = await db.fetchrow(
        f"SELECT min(l.month) AS first, max(l.month) AS last FROM sales_lines l "
        f"JOIN content_items c ON c.id = l.content_item_id WHERE {scope}", *args)
    if not span or not span["last"]:
        return {"status": "no_reports", "countries": [], "stores": []}
    last = date.fromisoformat(str(span["last"]))
    # The window's first month, or the first month the reports cover if later.
    first = max((last.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1),
                date.fromisoformat(str(span["first"])))
    args.append(first)
    n = len(args)
    by_country = await db.fetch(
        f"""SELECT l.country, sum(l.units)::bigint AS units FROM sales_lines l
            JOIN content_items c ON c.id = l.content_item_id
            WHERE {scope} AND l.month >= ${n} GROUP BY 1 ORDER BY 2 DESC""", *args)
    by_store = await db.fetch(
        f"""SELECT c.platform, sum(l.units)::bigint AS units FROM sales_lines l
            JOIN content_items c ON c.id = l.content_item_id
            WHERE {scope} AND l.month >= ${n} GROUP BY 1 ORDER BY 2 DESC""", *args)
    total = sum(r["units"] for r in by_country) or 1
    return {
        "status": "ok", "first_month": first.isoformat(), "last_month": last.isoformat(),
        "total_units": total if by_country else 0,
        "countries": [{"country": r["country"], "units": r["units"], "share": round(r["units"] / total, 4)}
                      for r in by_country[:15]],
        "stores": [{"platform": r["platform"], "units": r["units"], "share": round(r["units"] / total, 4)}
                   for r in by_store],
    }
