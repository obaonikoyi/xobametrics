"""
One-time copy of the old MongoDB data into PostgreSQL.

Runs at start-up only when MONGO_MIGRATION_URL is set and the Postgres
database has no users yet, so it can never overwrite live data and is safe to
leave configured across restarts. Everything is copied in one transaction:
either the whole import lands or none of it does.

MongoDB never enforced the rules the new schema does, so rows are cleaned on
the way in and every adjustment is counted in the summary that is logged:

- documents whose parent no longer exists (content for a deleted release) are
  skipped;
- duplicate imports of the same platform video are folded into one item and
  their snapshots moved onto it;
- more than one connection per platform per profile keeps the connected or
  most recent one;
- snapshots with an unreadable date are skipped; several for the same item,
  day and source keep the last;
- fields the new schema has no column for (and short-lived sign-in state) are
  dropped.
"""
import asyncio
import logging
from datetime import date, datetime

from database import db

logger = logging.getLogger("xobametrics.mongo_import")

# Parents before children, so foreign keys hold at every insert.
TABLES = [
    "users",
    "workspaces",
    "creator_profiles",
    "platform_connections",
    "releases",
    "content_items",
    "metric_snapshots",
    "release_match_dismissals",
    "reports",
    "files",
]

# Collections deliberately not carried over: sign-in attempts, OAuth state and
# the builder's old session tokens are all short-lived.
SKIPPED_COLLECTIONS = ("login_attempts", "oauth_states", "user_sessions")


def load_from_mongo(url: str, database: str) -> dict[str, list[dict]]:
    from pymongo import MongoClient

    client = MongoClient(url, serverSelectionTimeoutMS=10000)
    try:
        mdb = client[database]
        return {name: list(mdb[name].find({})) for name in TABLES}
    finally:
        client.close()


class _Summary:
    def __init__(self):
        self.copied: dict[str, int] = {}
        self.notes: dict[str, int] = {}

    def note(self, what: str, n: int = 1):
        self.notes[what] = self.notes.get(what, 0) + n

    def as_dict(self) -> dict:
        return {"copied": self.copied, "adjustments": self.notes}


def _clean(table: str, doc: dict, summary: _Summary) -> dict | None:
    columns = db.columns[table]
    row = {}
    for key, value in doc.items():
        if key == "_id":
            continue
        if key not in columns:
            summary.note(f"{table}: dropped field {key}")
            continue
        if value is None:
            # Omitted, so NOT NULL columns fall back to their defaults.
            continue
        kind = columns[key]
        if kind == "text" and isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif kind == "text" and value is not None and not isinstance(value, str):
            value = str(value)
        elif kind in ("integer", "bigint") and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0
        try:
            row[key] = db._coerce(table, key, value)
        except ValueError:
            summary.note(f"{table}: unreadable {key}")
            return None
    return row


def _dedupe(rows: list[dict], key, prefer, summary: _Summary, what: str) -> tuple[list[dict], dict]:
    """Keep one row per key; return the kept rows and a map of dropped id -> kept id."""
    chosen: dict = {}
    for row in rows:
        k = key(row)
        if k is None or k not in chosen:
            chosen[k if k is not None else id(row)] = row
            continue
        if prefer(row, chosen[k]):
            chosen[k] = row
    kept = list(chosen.values())
    kept_ids = {r.get("id") for r in kept}
    remap = {}
    for row in rows:
        if row.get("id") not in kept_ids:
            k = key(row)
            remap[row.get("id")] = chosen[k].get("id")
    if len(kept) != len(rows):
        summary.note(what, len(rows) - len(kept))
    return kept, remap


async def import_documents(collections: dict[str, list[dict]]) -> dict:
    """Copy Mongo-shaped documents into the (empty) Postgres schema."""
    summary = _Summary()
    rows: dict[str, list[dict]] = {}
    for table in TABLES:
        cleaned = []
        for doc in collections.get(table, []):
            row = _clean(table, doc, summary)
            if row is not None:
                cleaned.append(row)
        rows[table] = cleaned

    # Required columns and parents. Anything failing these would be rejected by
    # the database; skipping them here keeps the rest of the import.
    def keep(table, predicate, what):
        before = len(rows[table])
        rows[table] = [r for r in rows[table] if predicate(r)]
        if len(rows[table]) != before:
            summary.note(what, before - len(rows[table]))

    keep("users", lambda r: r.get("user_id") and r.get("email"), "users: missing id or email")
    for r in rows["users"]:
        r["email"] = r["email"].lower()
    rows["users"], _ = _dedupe(rows["users"], lambda r: r["email"], lambda a, b: False,
                               summary, "users: duplicate email")
    users = {r["user_id"] for r in rows["users"]}

    keep("workspaces", lambda r: r.get("id") and r.get("owner_id") in users,
         "workspaces: missing owner")
    workspaces = {r["id"] for r in rows["workspaces"]}

    keep("creator_profiles",
         lambda r: r.get("id") and r.get("owner_id") in users and r.get("workspace_id") in workspaces,
         "creator_profiles: missing owner or workspace")
    profiles = {r["id"] for r in rows["creator_profiles"]}

    def in_profile(r):
        return r.get("id") and r.get("profile_id") in profiles and r.get("owner_id") in users

    def workspace_ok(r):
        if r.get("workspace_id") not in workspaces:
            r["workspace_id"] = None
        return True

    keep("platform_connections", lambda r: in_profile(r) and r.get("platform") and workspace_ok(r),
         "platform_connections: missing profile")
    rows["platform_connections"], _ = _dedupe(
        rows["platform_connections"],
        lambda r: (r["profile_id"], r["platform"]),
        lambda a, b: (a.get("status") == "connected", str(a.get("connected_at") or ""))
        > (b.get("status") == "connected", str(b.get("connected_at") or "")),
        summary, "platform_connections: duplicate platform on a profile",
    )

    keep("releases",
         lambda r: in_profile(r) and r.get("title") and r.get("release_date") and workspace_ok(r),
         "releases: missing profile, title or date")
    releases = {r["id"] for r in rows["releases"]}

    keep("content_items",
         lambda r: in_profile(r) and r.get("release_id") in releases and r.get("title")
         and r.get("platform") and workspace_ok(r),
         "content_items: missing release or profile")
    rows["content_items"], content_remap = _dedupe(
        rows["content_items"],
        lambda r: (r["profile_id"], r["platform"], r["external_id"]) if r.get("external_id") else None,
        lambda a, b: False,
        summary, "content_items: duplicate platform import folded together",
    )
    content_release = {r["id"]: r["release_id"] for r in rows["content_items"]}

    for r in rows["metric_snapshots"]:
        if r.get("content_item_id") in content_remap:
            r["content_item_id"] = content_remap[r["content_item_id"]]
        # Point every observation at its item's current release.
        if r.get("content_item_id") in content_release:
            r["release_id"] = content_release[r["content_item_id"]]
        if not r.get("source"):
            r["source"] = "manual"
    keep("metric_snapshots",
         lambda r: r.get("id") and r.get("content_item_id") in content_release
         and r.get("profile_id") in profiles and r.get("date"),
         "metric_snapshots: missing item, profile or date")
    rows["metric_snapshots"], _ = _dedupe(
        rows["metric_snapshots"],
        lambda r: (r["content_item_id"], r["date"], r["source"]),
        lambda a, b: True,
        summary, "metric_snapshots: duplicate day for one item and source",
    )

    keep("release_match_dismissals",
         lambda r: r.get("profile_id") in profiles and r.get("owner_id") in users and r.get("match_key"),
         "release_match_dismissals: missing profile")
    for r in rows["release_match_dismissals"]:
        r.setdefault("release_ids", r["match_key"].split("::"))
    rows["release_match_dismissals"], _ = _dedupe(
        rows["release_match_dismissals"], lambda r: (r["profile_id"], r["match_key"]),
        lambda a, b: False, summary, "release_match_dismissals: duplicate",
    )

    keep("reports", lambda r: in_profile(r) and r.get("share_id") and r.get("title"),
         "reports: missing profile or share id")
    keep("files", lambda r: r.get("id") and r.get("owner_id") in users, "files: missing owner")
    for r in rows["files"]:
        if r.get("profile_id") not in profiles:
            r["profile_id"] = None

    async with db.transaction():
        for table in TABLES:
            # insert_many needs one column set per batch; old documents vary.
            groups: dict[tuple, list[dict]] = {}
            for r in rows[table]:
                groups.setdefault(tuple(sorted(r)), []).append(r)
            for batch in groups.values():
                await db.insert_many(table, batch)
            summary.copied[table] = len(rows[table])
    return summary.as_dict()


async def import_from_mongo_if_empty(url: str, database: str) -> dict | None:
    if await db.fetchval("SELECT EXISTS (SELECT 1 FROM users)"):
        logger.info("MONGO_MIGRATION_URL is set but Postgres already has users; not importing")
        return None
    collections = await asyncio.to_thread(load_from_mongo, url, database)
    summary = await import_documents(collections)
    logger.info("Imported MongoDB data into Postgres: %s (not copied: %s)", summary, SKIPPED_COLLECTIONS)
    return summary
