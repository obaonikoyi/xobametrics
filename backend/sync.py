"""Fail-closed sync until real platform adapters are implemented.

The old worker generated random growth for ordinary connected accounts. That
must never be presented as platform data. Demo generation belongs only in
seed.py; this module never synthesizes or updates metrics or last_synced_at.
"""
import logging

logger = logging.getLogger("xobametrics.sync")
INTEGRATION_MESSAGE = (
    "Live platform sync is not implemented yet. Upload a CSV export instead. "
    "No platform was contacted and no metrics were changed."
)


async def sync_content_item(content: dict, today=None) -> bool:
    """Do not append synthetic or carry-forward observations."""
    return False


async def sync_connection(connection: dict, today=None) -> int:
    """Kept for compatibility; never changes a connection's freshness."""
    return 0


async def sync_profile(profile_id: str, today=None) -> dict:
    return {
        "status": "not_implemented",
        "connections_synced": 0,
        "snapshots_created": 0,
        "synced_at": None,
        "message": INTEGRATION_MESSAGE,
    }


async def run_daily_sync():
    """Safe even if an older deployment still schedules this entry point."""
    logger.info("Live sync skipped: platform adapters are not implemented")
    return {
        "status": "not_implemented",
        "connections": 0,
        "snapshots_created": 0,
        "synced_at": None,
    }
