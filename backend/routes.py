import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, Request
from typing import Optional

from database import db
from auth import get_current_user
from models import (
    ProfileCreate, ConnectionCreate, ReleaseCreate, ContentCreate,
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


def _clean(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


async def _owned_profile(profile_id: str, user: dict) -> dict:
    prof = await db.creator_profiles.find_one({"id": profile_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    return prof


async def _owned_release(release_id: str, user: dict) -> dict:
    rel = await db.releases.find_one({"id": release_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not rel:
        raise HTTPException(status_code=404, detail="Release not found")
    return rel


# ---------- Workspaces & Profiles ----------
@api_router.get("/workspaces")
async def list_workspaces(user: dict = Depends(get_current_user)):
    workspaces = await db.workspaces.find({"owner_id": user["user_id"]}, {"_id": 0}).to_list(100)
    out = []
    for ws in workspaces:
        profiles = await db.creator_profiles.find({"workspace_id": ws["id"]}, {"_id": 0}).to_list(100)
        ws["profiles"] = profiles
        out.append(ws)
    return {"workspaces": out}


@api_router.post("/profiles")
async def create_profile(body: ProfileCreate, user: dict = Depends(get_current_user)):
    ws = await db.workspaces.find_one({"id": body.workspace_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.get("type") == "solo":
        await db.workspaces.update_one({"id": ws["id"]}, {"$set": {"type": "manager"}})
    prof = {
        "id": new_id("prof"),
        "workspace_id": body.workspace_id,
        "owner_id": user["user_id"],
        "name": body.name,
        "genre": body.genre,
        "avatar": body.avatar,
        "created_at": now_iso(),
    }
    await db.creator_profiles.insert_one(prof)
    return {"profile": _clean(prof)}


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
    conns = await db.platform_connections.find({"profile_id": profile_id}, {"_id": 0}).to_list(100)
    return {"connections": [_public_connection(c) for c in conns],
            "live_integrations_available": False,
            "message": sync_mod.INTEGRATION_MESSAGE}


@api_router.post("/connections")
async def create_connection(body: ConnectionCreate, user: dict = Depends(get_current_user)):
    await _owned_profile(body.profile_id, user)
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


@api_router.post("/connections/{connection_id}/reconnect")
async def reconnect(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await db.platform_connections.find_one({"id": connection_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    raise HTTPException(status_code=501, detail=sync_mod.INTEGRATION_MESSAGE)


@api_router.post("/connections/{connection_id}/sync")
async def sync_one_connection(connection_id: str, user: dict = Depends(get_current_user)):
    conn = await db.platform_connections.find_one({"id": connection_id, "owner_id": user["user_id"]}, {"_id": 0})
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
    releases = await db.releases.find({"profile_id": profile_id}, {"_id": 0}).to_list(1000)
    out = []
    for r in releases:
        rt = await analytics.release_totals(r["id"])
        r["reach"] = rt["totals"]["reach"]
        r["engagement"] = rt["totals"]["engagement"]
        r["content_count"] = rt["content_count"]
        r["last_synced"] = rt["last_synced"]
        out.append(r)
    out.sort(key=lambda x: x["release_date"], reverse=True)
    return {"releases": out}


@api_router.post("/releases")
async def create_release(body: ReleaseCreate, user: dict = Depends(get_current_user)):
    prof = await _owned_profile(body.profile_id, user)
    rel = {
        "id": new_id("rel"),
        "profile_id": body.profile_id,
        "workspace_id": prof["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.title,
        "release_date": body.release_date,
        "cover": body.cover or "#3B82F6",
        "description": body.description,
        "created_at": now_iso(),
    }
    await db.releases.insert_one(rel)
    return {"release": _clean(rel)}


@api_router.get("/releases/{release_id}")
async def get_release(release_id: str, user: dict = Depends(get_current_user)):
    rel = await _owned_release(release_id, user)
    content = await db.content_items.find({"release_id": release_id}, {"_id": 0}).to_list(1000)
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
    await db.content_items.insert_one(ci)
    return {"content": _clean(ci)}


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
    await db.files.insert_one({
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
    from datetime import date as _date
    release = {
        "id": new_id("rel"),
        "profile_id": body.profile_id,
        "workspace_id": prof["workspace_id"],
        "owner_id": user["user_id"],
        "title": body.release_title,
        "release_date": body.release_date,
        "cover": "#3B82F6",
        "description": f"Imported from CSV ({body.platform}).",
        "created_at": now_iso(),
    }
    await db.releases.insert_one(release)
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
        "published_at": body.release_date,
        "thumbnail": None,
        "created_at": now_iso(),
    }
    await db.content_items.insert_one(content)
    rel_date = _date.fromisoformat(body.release_date[:10])
    uses_plays = body.platform in analytics.PLAYS_PLATFORMS
    snap_docs = []
    for rec in norm:
        try:
            d = _date.fromisoformat(rec["date"][:10])
            offset = (d - rel_date).days
        except Exception:
            offset = None
        views = rec.get("views", 0)
        plays = rec.get("plays", 0)
        if uses_plays and plays == 0 and views:
            plays, views = views, 0
        reach = views + plays
        likes = rec.get("likes", 0)
        comments = rec.get("comments", 0)
        shares = rec.get("shares", 0)
        snap_docs.append({
            "id": new_id("snap"),
            "content_item_id": content["id"],
            "release_id": release["id"],
            "profile_id": body.profile_id,
            "date": rec["date"],
            "day_offset": offset,
            "views": int(views), "plays": int(plays),
            "likes": int(likes), "comments": int(comments), "shares": int(shares),
            "reach": int(reach), "engagement": int(likes + comments + shares),
            "followers": int(rec.get("followers", 0)),
        })
    if snap_docs:
        await db.metric_snapshots.insert_many(snap_docs)
    return {"release_id": release["id"], "snapshots": len(snap_docs)}


# ---------- Reports ----------
@api_router.get("/reports")
async def list_reports(profile_id: str, user: dict = Depends(get_current_user)):
    await _owned_profile(profile_id, user)
    reports = await db.reports.find({"profile_id": profile_id}, {"_id": 0}).to_list(200)
    reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
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
    await db.reports.insert_one(report)
    return {"report": _clean(report)}


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.reports.find_one({"id": report_id, "owner_id": user["user_id"]}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}


@api_router.get("/reports/shared/{share_id}")
async def get_shared_report(share_id: str):
    report = await db.reports.find_one({"share_id": share_id}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Shared report not found")
    public = {k: report.get(k) for k in
              ["id", "title", "share_id", "totals", "platform_breakdown",
               "releases", "summary", "recommendations", "created_at"]}
    return {"report": public}


# ---------- Demo seeding ----------
@api_router.post("/demo/seed")
async def seed_demo_data(user: dict = Depends(get_current_user)):
    ws = await db.workspaces.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    prof = await db.creator_profiles.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not ws or not prof:
        raise HTTPException(status_code=400, detail="Workspace not initialized")
    result = await seed_mod.seed_demo(user["user_id"], ws["id"], prof["id"])
    return result
