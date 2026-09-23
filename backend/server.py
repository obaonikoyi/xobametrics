import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware

from database import db
from auth import auth_router, hash_password
from google_auth import router as google_auth_router, _configured as google_signin_configured
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await db.close()


app = FastAPI(title="XobaMetrics API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(google_auth_router)
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
        "google_signin_configured": google_signin_configured(),
    }


@app.get("/api/ready")
async def ready():
    try:
        await asyncio.wait_for(db.fetchval("SELECT 1"), timeout=3)
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not ready")
    return {"status": "ready"}


async def cleanup_expired_state():
    """Drop OAuth/sign-in state and sessions that can no longer be used."""
    await db.execute("DELETE FROM oauth_states WHERE expires_at < now()")
    await db.execute(
        "DELETE FROM user_sessions WHERE expires_at < now() - interval '30 days'"
    )


async def startup():
    await db.connect()
    migration_url = os.environ.get("MONGO_MIGRATION_URL", "").strip()
    if migration_url:
        import mongo_import
        await mongo_import.import_from_mongo_if_empty(
            migration_url, os.environ.get("MONGO_MIGRATION_DB", "").strip() or os.environ.get("DB_NAME", "xobametrics")
        )
    try:
        storage.init_storage()
        logger.info("Object storage initialized")
    except Exception:
        logger.warning("Object storage unavailable; configure it before relying on archived uploads")
    await seed_admin()
    if not scheduler.running:
        scheduler.add_job(cleanup_expired_state, "interval", hours=1,
                          id="cleanup_expired_state", replace_existing=True)
        if os.environ.get("ENABLE_SCHEDULED_SYNC", "false").lower() == "true":
            scheduler.add_job(sync_mod.run_daily_sync, "cron", hour=4, minute=0,
                              id="daily_sync", replace_existing=True, misfire_grace_time=3600)
            logger.info("Sync entry point scheduled (04:00 UTC)")
        scheduler.start()


async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@xobametrics.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    existing = await db.find_one("users", {"email": admin_email})
    if existing is None:
        if not admin_password:
            logger.warning("ADMIN_PASSWORD not set; skipping admin seed")
            return
        user_id = new_id("user")
        await db.insert("users", {
            "user_id": user_id, "email": admin_email, "name": "Xoba Admin",
            "password_hash": hash_password(admin_password), "role": "admin",
            "auth_provider": "password", "beta_approved": True, "created_at": now_iso(),
        })
    else:
        user_id = existing["user_id"]
    demo_enabled = os.environ.get("ENABLE_DEMO_SEED", "false").lower() == "true"
    display_name = "Luna Eclipse" if demo_enabled else "Xoba Admin"
    ws = await db.find_one("workspaces", {"owner_id": user_id})
    if not ws:
        ws = {"id": new_id("ws"), "owner_id": user_id, "name": display_name,
              "type": "solo", "created_at": now_iso()}
        await db.insert("workspaces", ws)
    prof = await db.find_one("creator_profiles", {"owner_id": user_id})
    if not prof:
        prof = {"id": new_id("prof"), "workspace_id": ws["id"], "owner_id": user_id,
                "name": display_name, "genre": "Synthwave / Electronic" if demo_enabled else None,
                "avatar": None, "created_at": now_iso()}
        await db.insert("creator_profiles", prof)
    if not demo_enabled:
        return
    try:
        await seed_mod.seed_demo(user_id, ws["id"], prof["id"])
    except Exception:
        logger.warning("Demo seed failed")
