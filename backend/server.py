import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware

from database import db, client
from auth import auth_router, hash_password
from routes import api_router
from youtube import router as youtube_router, _configured as youtube_configured
from youtube_history import router as youtube_history_router
from soundcloud import router as soundcloud_router, _configured as soundcloud_configured
from models import new_id, now_iso
import storage
import seed as seed_mod
import sync as sync_mod
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("xobametrics")
scheduler = AsyncIOScheduler(timezone="UTC")
app = FastAPI(title="XobaMetrics API")
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(youtube_router)
app.include_router(youtube_history_router)
app.include_router(soundcloud_router)

_frontend = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
_origins = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _frontend and _frontend not in _origins:
    _origins.append(_frontend)
if "*" in _origins:
    raise RuntimeError("Explicit CORS origins are required; wildcard is not allowed")
if not _origins:
    logger.warning("No CORS origins configured; cross-origin browser requests will be blocked")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "xobametrics-api",
        "live_integrations_available": youtube_configured() or soundcloud_configured(),
        "youtube_configured": youtube_configured(),
        "soundcloud_configured": soundcloud_configured(),
    }


@app.get("/api/ready")
async def ready():
    try:
        await asyncio.wait_for(db.command("ping"), timeout=3)
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not ready")
    return {"status": "ready"}


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id")
    await db.user_sessions.create_index("session_token")
    await db.creator_profiles.create_index("owner_id")
    await db.releases.create_index("profile_id")
    await db.content_items.create_index("release_id")
    await db.content_items.create_index([("profile_id", 1), ("platform", 1), ("external_id", 1)])
    await db.metric_snapshots.create_index("content_item_id")
    await db.metric_snapshots.create_index([("content_item_id", 1), ("date", 1), ("source", 1)])
    await db.oauth_states.create_index("nonce", unique=True)
    try:
        storage.init_storage()
        logger.info("Object storage initialized")
    except Exception:
        logger.warning("Object storage unavailable; configure it before relying on archived uploads")
    await seed_admin()
    if os.environ.get("ENABLE_SCHEDULED_SYNC", "false").lower() == "true" and not scheduler.running:
        scheduler.add_job(sync_mod.run_daily_sync, "cron", hour=4, minute=0,
                          id="daily_sync", replace_existing=True, misfire_grace_time=3600)
        scheduler.start()
        logger.info("Sync entry point scheduled (04:00 UTC)")


@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()


async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@xobametrics.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    existing = await db.users.find_one({"email": admin_email}, {"_id": 0})
    if existing is None:
        if not admin_password:
            logger.warning("ADMIN_PASSWORD not set; skipping admin seed")
            return
        user_id = new_id("user")
        await db.users.insert_one({
            "user_id": user_id, "email": admin_email, "name": "Xoba Admin",
            "password_hash": hash_password(admin_password), "role": "admin",
            "auth_provider": "password", "beta_approved": True, "created_at": now_iso(),
        })
    else:
        user_id = existing["user_id"]
    demo_enabled = os.environ.get("ENABLE_DEMO_SEED", "false").lower() == "true"
    display_name = "Luna Eclipse" if demo_enabled else "Xoba Admin"
    ws = await db.workspaces.find_one({"owner_id": user_id}, {"_id": 0})
    if not ws:
        ws = {"id": new_id("ws"), "owner_id": user_id, "name": display_name,
              "type": "solo", "created_at": now_iso()}
        await db.workspaces.insert_one(ws)
    prof = await db.creator_profiles.find_one({"owner_id": user_id}, {"_id": 0})
    if not prof:
        prof = {"id": new_id("prof"), "workspace_id": ws["id"], "owner_id": user_id,
                "name": display_name, "genre": "Synthwave / Electronic" if demo_enabled else None,
                "avatar": None, "created_at": now_iso()}
        await db.creator_profiles.insert_one(prof)
    if not demo_enabled:
        return
    try:
        await seed_mod.seed_demo(user_id, ws["id"], prof["id"])
    except Exception:
        logger.warning("Demo seed failed")
