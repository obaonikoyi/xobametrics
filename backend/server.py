import os
import logging
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from database import db, client
from auth import auth_router, hash_password, verify_password
from routes import api_router
from models import new_id, now_iso
import storage
import seed as seed_mod
import sync as sync_mod
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("xobametrics")

scheduler = AsyncIOScheduler()

app = FastAPI(title="XobaMetrics API")

app.include_router(auth_router)
app.include_router(api_router)

_frontend = os.environ.get("FRONTEND_URL", "").strip()
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _frontend and _frontend not in _origins:
    _origins.append(_frontend)
if not _origins:
    _origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id")
    await db.user_sessions.create_index("session_token")
    await db.creator_profiles.create_index("owner_id")
    await db.releases.create_index("profile_id")
    await db.content_items.create_index("release_id")
    await db.metric_snapshots.create_index("content_item_id")

    try:
        storage.init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

    await seed_admin()

    # Scheduled platform-sync + snapshot worker (daily). Never live-calls APIs on page load.
    if not scheduler.running:
        scheduler.add_job(sync_mod.run_daily_sync, "cron", hour=4, minute=0,
                          id="daily_sync", replace_existing=True, misfire_grace_time=3600)
        scheduler.start()
        logger.info("Daily snapshot sync scheduled (04:00 UTC)")


@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()


async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@xobametrics.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email}, {"_id": 0})
    if existing is None:
        user_id = new_id("user")
        await db.users.insert_one({
            "user_id": user_id, "email": admin_email, "name": "Xoba Admin",
            "password_hash": hash_password(admin_password), "role": "admin",
            "auth_provider": "password", "beta_approved": True, "created_at": now_iso(),
        })
    else:
        user_id = existing["user_id"]
        if not verify_password(admin_password, existing.get("password_hash", "")):
            await db.users.update_one({"user_id": user_id},
                                      {"$set": {"password_hash": hash_password(admin_password)}})

    ws = await db.workspaces.find_one({"owner_id": user_id}, {"_id": 0})
    if not ws:
        ws = {"id": new_id("ws"), "owner_id": user_id, "name": "Luna Eclipse",
              "type": "solo", "created_at": now_iso()}
        await db.workspaces.insert_one(ws)
    prof = await db.creator_profiles.find_one({"owner_id": user_id}, {"_id": 0})
    if not prof:
        prof = {"id": new_id("prof"), "workspace_id": ws["id"], "owner_id": user_id,
                "name": "Luna Eclipse", "genre": "Synthwave / Electronic",
                "avatar": None, "created_at": now_iso()}
        await db.creator_profiles.insert_one(prof)
    try:
        await seed_mod.seed_demo(user_id, ws["id"], prof["id"])
    except Exception as e:
        logger.error(f"Demo seed failed: {e}")
