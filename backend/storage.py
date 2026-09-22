"""
Archival of uploaded CSVs, on a disk this deployment controls.

This used to POST every upload to a vendor's hosted object store and hold a key
from it. That put a third party in the path of user-uploaded data, and made the
archive unreadable to anyone without that vendor's account -- for files nothing
ever read back: `get_object` has no call sites in this repository.

So it writes to a directory instead. `UPLOAD_ARCHIVE_DIR` names it; with no
directory set, archiving is off and `put_object` raises, which the one call site
already handles by recording `storage_path = None` and importing the rows
anyway. Archiving has always been best-effort, and still is.

The signatures are unchanged, so routes, start-up and the existing tests keep
working against them.
"""
import os
from pathlib import Path

APP_NAME = "xobametrics"


class ArchiveUnavailable(RuntimeError):
    """No archive directory is configured, or it cannot be written."""


def _root() -> Path:
    directory = (os.environ.get("UPLOAD_ARCHIVE_DIR") or "").strip()
    if not directory:
        raise ArchiveUnavailable(
            "UPLOAD_ARCHIVE_DIR is not set, so uploaded files are not archived."
        )
    return Path(directory)


def _resolve(path: str) -> Path:
    """
    Where a stored object lives on disk.

    The name is built from a user id and generated hex, but it is still resolved
    and checked against the root: a path that escapes the archive directory is
    refused rather than written. Cheap, and the alternative is trusting that
    every future caller keeps building the name the same way.
    """
    root = _root().resolve()
    target = (root / path).resolve()
    if root not in target.parents:
        raise ArchiveUnavailable("Refusing to write outside the archive directory.")
    return target


def init_storage(force: bool = False) -> str:
    """
    Check the archive is usable and return where it is.

    Called once at start-up so a misconfigured archive is reported in the log
    then, rather than on a user's first upload. `force` is kept because the
    start-up path passes it; there is no cached credential to refresh now.
    """
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    if not os.access(root, os.W_OK):
        raise ArchiveUnavailable(f"Archive directory {root} is not writable.")
    return str(root)


def put_object(path: str, data: bytes, content_type: str) -> dict:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": path, "bytes": len(data), "content_type": content_type}


def get_object(path: str):
    target = _resolve(path)
    if not target.is_file():
        raise ArchiveUnavailable(f"No archived object at {path}.")
    # Only CSV uploads are archived, so no separate content type is stored.
    return target.read_bytes(), "text/csv"
