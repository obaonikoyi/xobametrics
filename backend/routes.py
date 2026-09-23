import uuid
import re
import unicodedata
from datetime import date as _date
from difflib import SequenceMatcher
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, Request
from typing import Optional

from database import db
from auth import get_current_user
from models import (
    ProfileCreate, ConnectionCreate, ReleaseCreate, ReleaseUpdate, ReleaseMergeRequest, ContentCreate,
    AiInsightRequest, AiAskRequest, ReportCreate, CsvCommitRequest,
    new_id, now_iso,
)
import analytics
import ai
import csv_import
import storage
import seed as seed_mod
import sync as sync_mod

api_router = APIRouter(prefix="/api")


async def _owned_profile(profile_id: str, user: dict) -> dict:
    prof = await db.find_one("creator_profiles", {"id": profile_id, "owner_id": user["user_id"]})
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    return prof


async def _owned_release(release_id: str, user: dict) -> dict:
    rel = await db.find_one("releases", {"id": release_id, "owner_id": user["user_id"]})
    if not rel:
        raise HTTPException(status_code=404, detail="Release not found")
    return rel


def _release_date(value: str) -> str:
    try:
        return _date.fromisoformat(str(value)[:10]).isoformat()
    except Exception:
        raise HTTPException(status_code=422, detail="Release date must be YYYY-MM-DD")


_MATCH_NOISE = {
    "official", "audio", "video", "music", "visualizer", "visualiser",
    "lyric", "lyrics", "short", "shorts", "teaser", "promo", "clip",
    "full", "mv", "4k", "hd",
}


def _normalized_release_title(title: str) -> tuple[str, set[str]]:
    text = unicodedata.normalize("NFKD", str(title or "")).lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    tokens = [t for t in text.split() if t not in _MATCH_NOISE]
    return " ".join(tokens), set(tokens)


def _match_score(a: dict, b: dict) -> tuple[float, int]:
    na, ta = _normalized_release_title(a.get("title"))
    nb, tb = _normalized_release_title(b.get("title"))
    if not na or not nb:
        return 0.0, 9999
    try:
        gap = abs((_date.fromisoformat(a["release_date"][:10]) - _date.fromisoformat(b["release_date"][:10])).days)
    except Exception:
        gap = 9999
    if na == nb:
        base = 0.96
    else:
        if not ta or not tb:
            return 0.0, gap
        jaccard = len(ta & tb) / max(1, len(ta | tb))
        ratio = SequenceMatcher(None, na, nb).ratio()
        base = 0.55 * ratio + 0.45 * jaccard
    if gap <= 14:
        base += 0.08
    elif gap <= 45:
        base += 0.04
    elif gap > 120 and na != nb:
        base -= 0.12
    return min(1.0, max(0.0, base)), gap


def _match_key(a: str, b: str) -> str:
    return "::".join(sorted((a, b)))


# ---------- Workspaces & Profiles ----------
@api_router.get("/workspaces")
async def list_workspaces(user: dict = Depends(get_current_user)):
    workspaces = await db.find("workspaces", {"owner_id": user["user_id"]}, order_by="created_at")
    profiles = await db.find("creator_profiles", {"owner_id": user["user_id"]}, order_by="created_at")
    for ws in workspaces:
        ws["profiles"] = [p for p in profiles if p["workspace_id"] == ws["id"]]
    return {"workspaces": workspaces}


@api_router.post("/profiles")
async def create_profile(body: ProfileCreate, user: dict = Depends(get_current_user)):
    ws = await db.find_one("workspaces", {"id": body.workspace_id, "owner_id": user["user_id"]})
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.get("type") == "solo":
        await db.update("workspaces", {"id": ws["id"]}, {"type": "manager"})
    prof = {
        "id": new_id("prof"),
        "workspace_id": body.workspace_id,
        "owner_id": user["user_id"],
        "name": body.name,
        "genre": body.genre,
        "avatar": body.avatar,
        "created_at": now_iso(),
    }
    await db.insert("creator_profiles", prof)
    return {"profile": prof}


# ---------- Platform Connections ----------
def _public_connection(conn: dict) -> dict:
    # No real OAuth adapters exist yet. Do not expose legacy stub statuses as
    # verified connections, and never serialize future token fields to clients.
    public = {key: conn.get(key) for key in
              ("id", "profile_id", "platform", "account_name", "source")}
    public.update({"status": "needs_auth", "last_synced_at": None,
                   "integration_state": "not_implemented",
                   "status_message": sync_mod.INTEGRATION_MESSAGE})
    return public


@api_router.get("/connections")
async def list_connections(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    conns = await db.find("platform_connections", {"profile_id": profile_id})
    return {"connections": [_public_connection(c) for c in conns],
            "live_integrations_available": False,
            "message": sync_mod.INTEGRATION_MESSAGE}


@api_router.post("/connections")
async def create_connection(body: ConnectionCreate, user: dict = Depends(get_current_user)):
    await _owned_profile(body.profile_id, user)
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


@api_router.post("/connections/{connection_id}/reconnect")
async def reconnect(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await db.find_one("platform_connections", {"id": connection_id, "owner_id": user["user_id"]})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


@api_router.post("/connections/{connection_id}/sync")
async def sync_one_connection(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await db.find_one("platform_connections", {"id": connection_id, "owner_id": user["user_id"]})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


@api_router.post("/sync/run")
async def sync_run(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


# ---------- Releases & Content ----------
@api_router.get("/releases")
async def list_releases(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    releases = await db.find("releases", {"profile_id": profile_id})
    rollups = await analytics.profile_release_totals(profile_id)
    for r in releases:
        rt = rollups.get(r["id"]) or analytics.empty_release_totals()
        r["reach"] = rt["totals"]["reach"]
        r["engagement"] = rt["totals"]["engagement"]
        r["content_count"] = rt["content_count"]
        r["last_synced"] = rt["last_synced"]
    releases.sort(key=lambda x: x["release_date"], reverse=True)
    return {"releases": releases}


@api_router.post("/releases")
async def create_release(body: ReleaseCreate, user: dict = Depends(get_current_user)):
    prof = await _owned_profile(body.profile_id, user)
    rel = {
        "id": new_id("rel"),
        "profile_id": body.profile_id,
        "workspace_id": prof["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.title,
        "release_date": _release_date(body.release_date),
        "cover": body.cover or "#3B82F6",
        "description": body.description,
        "created_at": now_iso(),
    }
    await db.insert("releases", rel)
    return {"release": rel}


@api_router.patch("/releases/{release_id}")
async def update_release(release_id: str, body: ReleaseUpdate, user: dict = Depends(get_current_user)):
    await _owned_release(release_id, user)
    changes = body.model_dump(exclude_unset=True)
    if "release_date" in changes and changes["release_date"] is not None:
        changes["release_date"] = _release_date(changes["release_date"])
    if not changes:
        return {"release": await _owned_release(release_id, user)}
    changes["updated_at"] = now_iso()
    await db.update("releases", {"id": release_id, "owner_id": user["user_id"]}, changes)
    return {"release": await _owned_release(release_id, user)}


@api_router.post("/releases/{target_release_id}/merge")
async def merge_releases(
    target_release_id: str,
    body: ReleaseMergeRequest,
    user: dict = Depends(get_current_user),
):
    target = await _owned_release(target_release_id, user)
    source_ids = list(dict.fromkeys(
        rid for rid in body.source_release_ids if rid and rid != target_release_id
    ))
    if not source_ids:
        raise HTTPException(status_code=400, detail="Select at least one other release to merge")

    sources = await db.find("releases", {
        "id": source_ids,
        "owner_id": user["user_id"],
        "profile_id": target["profile_id"],
    })
    if len(sources) != len(source_ids):
        raise HTTPException(status_code=404, detail="One or more selected releases were not found")

    changes = {
        "source": "organized",
        "source_external_id": None,
        "updated_at": now_iso(),
    }
    if body.title is not None:
        changes["title"] = body.title
    if body.release_date is not None:
        changes["release_date"] = _release_date(body.release_date)
    if body.description is not None:
        changes["description"] = body.description

    # All or nothing: a failure part-way must not leave content split across
    # a half-merged campaign.
    async with db.transaction():
        content_moved = await db.update(
            "content_items",
            {"release_id": source_ids, "owner_id": user["user_id"], "profile_id": target["profile_id"]},
            {"release_id": target_release_id},
        )
        await db.execute(
            """
            UPDATE metric_snapshots s SET release_id = $1
            FROM content_items c
            WHERE c.id = s.content_item_id AND c.release_id = $1 AND s.release_id <> $1
            """,
            target_release_id,
        )
        await db.update("releases", {"id": target_release_id, "owner_id": user["user_id"]}, changes)
        await db.delete("releases", {
            "id": source_ids, "owner_id": user["user_id"], "profile_id": target["profile_id"],
        })

    merged = await _owned_release(target_release_id, user)
    return {
        "release": merged,
        "merged_release_ids": source_ids,
        "content_moved": content_moved,
        "content_count": await db.count("content_items", {"release_id": target_release_id}),
    }


@api_router.get("/release-match-suggestions")
async def release_match_suggestions(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    releases = await db.find("releases", {"profile_id": profile_id, "owner_id": user["user_id"]})
    if len(releases) < 2:
        return {"suggestions": []}

    release_ids = [r["id"] for r in releases]
    content = await db.fetch(
        "SELECT release_id, platform FROM content_items WHERE release_id = ANY($1) AND owner_id = $2",
        release_ids, user["user_id"],
    )
    platforms = {rid: set() for rid in release_ids}
    for item in content:
        if item.get("release_id") in platforms and item.get("platform"):
            platforms[item["release_id"]].add(item["platform"])

    dismissed_docs = await db.find(
        "release_match_dismissals", {"profile_id": profile_id, "owner_id": user["user_id"]}
    )
    dismissed = {d.get("match_key") for d in dismissed_docs}

    suggestions = []
    for i, a in enumerate(releases):
        for b in releases[i + 1:]:
            key = _match_key(a["id"], b["id"])
            if key in dismissed:
                continue
            pa = platforms.get(a["id"], set())
            pb = platforms.get(b["id"], set())
            # A match should add at least some platform diversity. This keeps
            # the feature focused on cross-platform campaign organization.
            if not pa or not pb or len(pa | pb) < 2:
                continue
            score, gap = _match_score(a, b)
            if score < 0.76:
                continue

            # Prefer an already-organized campaign, otherwise the earlier
            # release as the merge target because Day 0 should normally be the
            # campaign's first publication date.
            if a.get("source") == "organized" and b.get("source") != "organized":
                target_id = a["id"]
            elif b.get("source") == "organized" and a.get("source") != "organized":
                target_id = b["id"]
            else:
                target_id = min((a, b), key=lambda r: r.get("release_date") or "9999-12-31")["id"]

            confidence = "strong" if score >= 0.90 else "possible"
            suggestions.append({
                "match_key": key,
                "score": round(score, 3),
                "confidence": confidence,
                "date_gap_days": gap,
                "suggested_target_id": target_id,
                "reason": (
                    "Very similar title across platforms"
                    if score >= 0.90
                    else "Similar title and release timing across platforms"
                ),
                "release_a": {
                    "id": a["id"], "title": a["title"], "release_date": a["release_date"],
                    "cover": a.get("cover"), "platforms": sorted(pa),
                },
                "release_b": {
                    "id": b["id"], "title": b["title"], "release_date": b["release_date"],
                    "cover": b.get("cover"), "platforms": sorted(pb),
                },
            })

    suggestions.sort(key=lambda s: (-s["score"], s["date_gap_days"]))
    return {"suggestions": suggestions[:30]}


@api_router.post("/release-match-suggestions/dismiss")
async def dismiss_release_match(
    profile_id: str,
    release_a: str,
    release_b: str,
    user: dict = Depends(get_current_user),
):
    await _owned_profile(profile_id, user)
    if release_a == release_b:
        raise HTTPException(status_code=400, detail="A release cannot be matched with itself")
    owned = await db.count("releases", {
        "id": [release_a, release_b],
        "profile_id": profile_id,
        "owner_id": user["user_id"],
    })
    if owned != 2:
        raise HTTPException(status_code=404, detail="One or more releases were not found")
    key = _match_key(release_a, release_b)
    await db.upsert(
        "release_match_dismissals",
        {
            "owner_id": user["user_id"],
            "profile_id": profile_id,
            "match_key": key,
            "release_ids": sorted([release_a, release_b]),
            "dismissed_at": now_iso(),
        },
        conflict=("profile_id", "match_key"),
    )
    return {"ok": True, "match_key": key}


@api_router.get("/releases/{release_id}")
async def get_release(release_id: str, user: dict = Depends(get_current_user)):
    rel = await _owned_release(release_id, user)
    content = await db.find("content_items", {"release_id": release_id}, order_by="created_at")
    latest = await analytics._latest_snapshots_by_content([c["id"] for c in content])
    for c in content:
        snap = latest.get(c["id"], {})
        c["metrics"] = {k: snap.get(k, 0) for k in analytics.METRIC_KEYS}
        c["last_synced"] = snap.get("date")
    rt = await analytics.release_totals(release_id)
    return {"release": rel, "rollup": rt, "content": content}


@api_router.post("/content")
async def create_content(body: ContentCreate, user: dict = Depends(get_current_user)):
    rel = await _owned_release(body.release_id, user)
    ci = {
        "id": new_id("ci"),
        "release_id": body.release_id,
        "profile_id": rel["profile_id"],
        "workspace_id": rel["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.title,
        "platform": body.platform,
        "content_type": body.content_type,
        "url": body.url,
        "published_at": body.published_at or rel["release_date"],
        "thumbnail": body.thumbnail,
        "created_at": now_iso(),
    }
    await db.insert("content_items", ci)
    return {"content": ci}


# ---------- Analytics ----------
@api_router.get("/analytics/overview")
async def overview(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    return await analytics.profile_overview(profile_id)


@api_router.get("/analytics/release-timeseries/{release_id}")
async def timeseries(release_id: str, metric: str = "reach", user: dict = Depends(get_current_user)):
    await _owned_release(release_id, user)
    return await analytics.release_timeseries(release_id, metric)


@api_router.get("/analytics/release-race")
async def race(profile_id: str, release_ids: str, metric: str = "reach", max_day: int = 90,
               user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    ids = [x for x in release_ids.split(",") if x]
    return await analytics.release_race(profile_id, ids, metric, max_day)


# ---------- AI ----------
@api_router.post("/ai/insights")
async def ai_insights(body: AiInsightRequest, user: dict = Depends(get_current_user)):
    await _owned_profile(body.profile_id, user)
    if body.release_id:
        release = await _owned_release(body.release_id, user)
        if release["profile_id"] != body.profile_id:
            raise HTTPException(status_code=404, detail="Release not found")
    return await ai.generate_insight(body.profile_id, body.release_id)


@api_router.post("/ai/ask")
async def ai_ask(body: AiAskRequest, user: dict = Depends(get_current_user)):
    await _owned_profile(body.profile_id, user)
    result = await ai.answer_question(body.profile_id, body.question)
    result.pop("facts_used", None)
    return result


# ---------- CSV ----------
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMPORT_ROWS = 5000


@api_router.post("/csv/upload")
async def csv_upload(request: Request, file: UploadFile = File(...), profile_id: str = Form(...),
                     user: dict = Depends(get_current_user)):
    # Require a non-simple header; CORS restricts allowed browser origins.
    if request.headers.get("x-requested-with") != "XobaMetrics":
        raise HTTPException(status_code=403, detail="Invalid request origin")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")
    try:
        declared = int(request.headers.get("content-length", 0))
    except ValueError:
        declared = 0
    if declared > MAX_UPLOAD_BYTES + 4096:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    await _owned_profile(profile_id, user)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    headers, rows, suggested = csv_import.parse_csv(raw)
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {MAX_IMPORT_ROWS})")
    preview = csv_import.normalize_rows(rows, suggested)
    try:
        path = f"{storage.APP_NAME}/uploads/{user['user_id']}/{uuid.uuid4().hex}.csv"
        storage.put_object(path, raw, "text/csv")
    except Exception:
        path = None
    await db.insert("files", {
        "id": new_id("file"),
        "owner_id": user["user_id"],
        "profile_id": profile_id,
        "storage_path": path,
        "original_filename": file.filename,
        "content_type": "text/csv",
        "is_deleted": False,
        "created_at": now_iso(),
    })
    return {"headers": headers, "rows": rows, "suggested_mapping": suggested,
            "preview": preview[:30], "row_count": len(rows)}


@api_router.post("/csv/commit")
async def csv_commit(body: CsvCommitRequest, user: dict = Depends(get_current_user)):
    prof = await _owned_profile(body.profile_id, user)
    if len(body.rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {MAX_IMPORT_ROWS})")
    norm = csv_import.normalize_rows(body.rows, body.mapping)
    if not norm:
        raise HTTPException(status_code=400, detail="No valid rows found after normalization")
    release_date = _release_date(body.release_date)
    bad_dates = []
    for rec in norm:
        try:
            _date.fromisoformat(rec["date"][:10])
        except ValueError:
            bad_dates.append(rec["date"])
    if bad_dates:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(bad_dates)} row(s) have dates that are not YYYY-MM-DD "
                f"(for example \"{bad_dates[0]}\"). Reformat the date column and try again."
            ),
        )
    release = {
        "id": new_id("rel"),
        "profile_id": body.profile_id,
        "workspace_id": prof["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.release_title,
        "release_date": release_date,
        "cover": "#3B82F6",
        "description": f"Imported from CSV ({body.platform}).",
        "created_at": now_iso(),
    }
    content = {
        "id": new_id("ci"),
        "release_id": release["id"],
        "profile_id": body.profile_id,
        "workspace_id": prof["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.content_title or body.release_title,
        "platform": body.platform,
        "content_type": body.content_type or "track",
        "url": None,
        "published_at": release_date,
        "thumbnail": None,
        "created_at": now_iso(),
    }
    rel_date = _date.fromisoformat(release_date)
    uses_plays = body.platform in analytics.PLAYS_PLATFORMS
    # Keyed by day: a file that repeats a date keeps its last row, as the
    # database allows one manual observation per item per day.
    snap_docs = {}
    for rec in norm:
        d = _date.fromisoformat(rec["date"][:10])
        offset = (d - rel_date).days
        views = rec.get("views", 0)
        plays = rec.get("plays", 0)
        if uses_plays and plays == 0 and views:
            plays, views = views, 0
        reach = views + plays
        likes = rec.get("likes", 0)
        comments = rec.get("comments", 0)
        shares = rec.get("shares", 0)
        snap_docs[d] = {
            "id": new_id("snap"),
            "content_item_id": content["id"],
            "release_id": release["id"],
            "profile_id": body.profile_id,
            "date": d,
            "day_offset": offset,
            "views": int(views), "plays": int(plays),
            "likes": int(likes), "comments": int(comments), "shares": int(shares),
            "reach": int(reach), "engagement": int(likes + comments + shares),
            "followers": int(rec.get("followers", 0)),
            "source": "manual",
        }
    async with db.transaction():
        await db.insert("releases", release)
        await db.insert("content_items", content)
        await db.insert_many("metric_snapshots", list(snap_docs.values()))
    return {"release_id": release["id"], "snapshots": len(snap_docs)}


# ---------- Reports ----------
@api_router.get("/reports")
async def list_reports(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    reports = await db.find("reports", {"profile_id": profile_id}, order_by="created_at DESC")
    return {"reports": reports}


@api_router.post("/reports")
async def create_report(body: ReportCreate, user: dict = Depends(get_current_user)):
    await _owned_profile(body.profile_id, user)
    overview_data = await analytics.profile_overview(body.profile_id)
    insight = await ai.generate_insight(body.profile_id, None)
    report = {
        "id": new_id("rep"),
        "profile_id": body.profile_id,
        "owner_id": user["user_id"],
        "title": body.title,
        "share_id": uuid.uuid4().hex,
        "totals": overview_data["totals"],
        "platform_breakdown": overview_data["platform_breakdown"],
        "releases": overview_data["releases"],
        "summary": insight.get("summary"),
        "recommendations": insight.get("recommendations", []),
        "created_at": now_iso(),
    }
    await db.insert("reports", report)
    return {"report": report}


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.find_one("reports", {"id": report_id, "owner_id": user["user_id"]})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}


@api_router.get("/reports/shared/{share_id}")
async def get_shared_report(share_id: str):
    report = await db.find_one("reports", {"share_id": share_id})
    if not report:
        raise HTTPException(status_code=404, detail="Shared report not found")
    public = {k: report.get(k) for k in
              ["id", "title", "share_id", "totals", "platform_breakdown",
               "releases", "summary", "recommendations", "created_at"]}
    return {"report": public}


# ---------- Demo seeding ----------
@api_router.post("/demo/seed")
async def seed_demo_data(user: dict = Depends(get_current_user)):
    ws = await db.find_one("workspaces", {"owner_id": user["user_id"]})
    prof = await db.find_one("creator_profiles", {"owner_id": user["user_id"]})
    if not ws or not prof:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    result = await seed_mod.seed_demo(user["user_id"], ws["id"], prof["id"])
    return result
